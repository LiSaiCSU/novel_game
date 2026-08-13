"""Authentication primitives and request identity dependencies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated

import sqlalchemy as sa
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Cookie, Depends, Header, HTTPException, Request, status

import database.session as db_session
from apps.api.deps import settings_dep
from database.models.platform import AuthSessionORM, UserORM, UserRoleORM
from engine.core.config import Settings

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    email: str
    display_name: str
    roles: frozenset[str]
    auth_session_id: str
    csrf_hash: str
    analytics_consent: bool = False

    def has_role(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if len(email) > 320 or not _EMAIL.fullmatch(email):
        raise ValueError("invalid email address")
    return email


@lru_cache(maxsize=1)
def password_hasher() -> PasswordHasher:
    return PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 256:
        raise ValueError("password must contain between 12 and 256 characters")
    return password_hasher().hash(password)


def verify_password(encoded: str, password: str) -> bool:
    try:
        return password_hasher().verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def opaque_token(bytes_: int = 32) -> str:
    return secrets.token_urlsafe(bytes_)


def token_hash(token: str, pepper: str) -> str:
    return hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _totp(secret: str, counter: int) -> str:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{binary % 1_000_000:06d}"


def verify_totp(secret: str, code: str, *, now: float | None = None) -> int | None:
    candidate = re.sub(r"\s", "", code)
    if not re.fullmatch(r"\d{6}", candidate):
        return None
    counter = int((time.time() if now is None else now) // 30)
    for drift in (-1, 0, 1):
        checked = counter + drift
        if hmac.compare_digest(_totp(secret, checked), candidate):
            return checked
    return None


class SecretBox:
    """Envelope-ready credential encryption with a deployment-owned master key."""

    def __init__(self, key: str) -> None:
        if not key:
            raise ValueError("credential encryption key is not configured")
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        import base64

        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("credential ciphertext cannot be decrypted") from exc


async def optional_principal(
    request: Request,
    settings: Settings = Depends(settings_dep),
) -> Principal | None:
    raw = request.cookies.get(settings.auth_cookie_name)
    if not raw:
        return None
    digest = token_hash(raw, settings.auth_pepper)
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        stmt = (
            sa.select(AuthSessionORM, UserORM)
            .join(UserORM, UserORM.id == AuthSessionORM.user_id)
            .where(
                AuthSessionORM.token_hash == digest,
                AuthSessionORM.revoked_at.is_(None),
                AuthSessionORM.expires_at > datetime.now(UTC),
                UserORM.status == "active",
            )
        )
        row = (await session.execute(stmt)).first()
        if row is None:
            return None
        auth_session, user = row
        roles = (
            await session.execute(sa.select(UserRoleORM.role).where(UserRoleORM.user_id == user.id))
        ).scalars().all()
        # Device recency is telemetry, not part of authorisation. Updating it
        # on every request creates a write hotspot on the session row and can
        # serialize otherwise read-only traffic. A five-minute resolution is
        # sufficient for the device list and login-anomaly UI.
        now = datetime.now(UTC)
        last_seen = auth_session.last_seen_at
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        if last_seen < now - timedelta(minutes=5):
            auth_session.last_seen_at = now
            await session.commit()
        return Principal(
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            roles=frozenset(roles),
            auth_session_id=auth_session.id,
            csrf_hash=auth_session.csrf_token_hash,
            analytics_consent=user.analytics_consent,
        )


async def current_principal(
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> Principal:
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    return principal


async def verified_principal(
    principal: Annotated[Principal, Depends(current_principal)],
    settings: Settings = Depends(settings_dep),
) -> Principal:
    if not settings.require_verified_email:
        return principal
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        verified = await session.scalar(
            sa.select(UserORM.email_verified_at).where(UserORM.id == principal.user_id)
        )
    if verified is None:
        raise HTTPException(status_code=403, detail="email verification required")
    return principal


async def require_csrf(
    request: Request,
    principal: Annotated[Principal, Depends(verified_principal)],
    settings: Settings = Depends(settings_dep),
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    csrf_cookie: Annotated[str | None, Cookie(alias="ng_csrf")] = None,
) -> Principal:
    # The configured cookie name can differ; Request is authoritative.
    raw_cookie = request.cookies.get(settings.csrf_cookie_name) or csrf_cookie
    if not csrf_header or not raw_cookie or not hmac.compare_digest(csrf_header, raw_cookie):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    if not hmac.compare_digest(
        token_hash(csrf_header, settings.auth_pepper), principal.csrf_hash
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return principal


def require_roles(*roles: str):
    async def dependency(
        principal: Annotated[Principal, Depends(verified_principal)],
        settings: Settings = Depends(settings_dep),
    ) -> Principal:
        if not principal.has_role(*roles):
            raise HTTPException(status_code=403, detail="insufficient role")
        await require_admin_mfa(principal, settings)
        return principal

    return dependency


async def require_admin_mfa(principal: Principal, settings: Settings) -> None:
    if not settings.admin_mfa_required or not principal.has_role("admin"):
        return
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        user = await session.get(UserORM, principal.user_id)
        auth_session = await session.get(AuthSessionORM, principal.auth_session_id)
    if user is None or user.mfa_enabled_at is None:
        raise HTTPException(
            status_code=403,
            detail={"code": "admin_mfa_enrollment_required", "message": "administrator MFA enrollment required"},
        )
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.mfa_step_up_minutes)
    verified_at = auth_session.mfa_verified_at if auth_session else None
    if verified_at is not None and verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=UTC)
    if verified_at is None or verified_at < cutoff:
        raise HTTPException(
            status_code=403,
            detail={"code": "admin_mfa_step_up_required", "message": "administrator MFA verification required"},
        )


def require_role_csrf(*roles: str):
    async def dependency(
        principal: Annotated[Principal, Depends(require_csrf)],
        settings: Settings = Depends(settings_dep),
    ) -> Principal:
        if not principal.has_role(*roles):
            raise HTTPException(status_code=403, detail="insufficient role")
        await require_admin_mfa(principal, settings)
        return principal

    return dependency


def session_expiry(settings: Settings) -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.auth_session_days)
