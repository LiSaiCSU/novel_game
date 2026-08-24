"""Public email/password authentication API."""

from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import quote

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator

from apps.api.deps import settings_dep, uow_dep
from apps.api.emailer import send_email
from apps.api.platform_settings import (
    ANNOUNCEMENT_KEY,
    EMPTY_ANNOUNCEMENT,
    default_monthly_quota,
    read_setting,
)
from apps.api.rate_limit import rate_limiter
from apps.api.security import (
    Principal,
    SecretBox,
    current_principal,
    hash_password,
    new_totp_secret,
    normalize_email,
    opaque_token,
    require_csrf,
    session_expiry,
    token_hash,
    verified_principal,
    verify_password,
    verify_totp,
)
from database.bootstrap import configured_super_admin_emails
from database.models.platform import (
    AuditLogORM,
    AuthSessionORM,
    EmailTokenORM,
    UserORM,
    UserRoleORM,
)
from database.repositories.sql import SqlUnitOfWork
from engine.core.config import Settings
from engine.core.ids import new_id

router = APIRouter(prefix="/auth", tags=["v1-auth"])

VERIFICATION_CODE_DIGITS = 4
# One shared message for every failure mode of a verification attempt: a
# wrong code, an expired code and an unknown address must be indistinguishable
# so the endpoint cannot be used to enumerate registered addresses.
INVALID_CODE_DETAIL = "verification code is invalid or expired"


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field(default="", max_length=80)
    locale: str = Field(default="zh-CN", max_length=20)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=1, max_length=32)

    @field_validator("code")
    @classmethod
    def only_digits(cls, value: str) -> str:
        # Codes are copied out of a mail client, so spaces and full-width
        # digits arrive routinely. Normalise instead of rejecting.
        digits = "".join(
            str(int(character)) for character in value.strip() if character.isdecimal()
        )
        if len(digits) != VERIFICATION_CODE_DIGITS:
            raise ValueError(f"code must contain {VERIFICATION_CODE_DIGITS} digits")
        return digits


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(TokenRequest):
    password: str = Field(min_length=12, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)
    # An account with MFA must prove possession again before changing the
    # primary credential. Recovery codes are accepted and consumed here too.
    mfa_code: str = Field(default="", max_length=32)


class MfaEnrollRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class MfaDisableRequest(MfaCodeRequest):
    password: str = Field(min_length=1, max_length=256)


class MfaRecoveryCodesRequest(MfaDisableRequest):
    """Reissue recovery codes after password + possession verification."""


class UserView(BaseModel):
    id: str
    email: str
    display_name: str
    locale: str
    verified: bool
    roles: list[str]


class SessionView(BaseModel):
    id: str
    user_agent: str
    ip_address: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool = False


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def _set_auth_cookies(
    response: Response, settings: Settings, session_token: str, csrf_token: str
) -> None:
    max_age = settings.auth_session_days * 86400
    response.set_cookie(
        settings.auth_cookie_name,
        session_token,
        max_age=max_age,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        max_age=max_age,
        secure=settings.auth_cookie_secure,
        httponly=False,
        samesite="lax",
        path="/",
    )


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.auth_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


async def _issue_email_token(
    uow: SqlUnitOfWork, settings: Settings, user_id: str, purpose: str
) -> str:
    raw = opaque_token()
    uow.session.add(
        EmailTokenORM(
            id=new_id(),
            user_id=user_id,
            purpose=purpose,
            token_hash=token_hash(raw, settings.auth_pepper),
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.email_token_minutes),
        )
    )
    return raw


def _code_digest(row_id: str, purpose: str, code: str, settings: Settings) -> str:
    """Bind a short code to the row that issued it.

    ``email_tokens.token_hash`` is globally unique.  Hashing the bare code
    would collide across users after a few hundred signups, and hashing
    ``user + code`` would still collide whenever the same user is re-issued
    the same code.  The row id makes the digest unique by construction, and
    lookups go through ``user_id + purpose`` rather than through the digest.
    """
    return token_hash(f"{purpose}:{row_id}:{code}", settings.auth_pepper)


def _new_verification_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(VERIFICATION_CODE_DIGITS))


async def _issue_email_code(
    uow: SqlUnitOfWork, settings: Settings, user_id: str, purpose: str
) -> str:
    """Replace any live code for this purpose with a freshly generated one."""
    now = datetime.now(UTC)
    # Only one code may be redeemable at a time. Otherwise "resend" widens the
    # guessable keyspace instead of replacing it, and a user who resent twice
    # would not know which of the three mails is the live one.
    await uow.session.execute(
        sa.update(EmailTokenORM)
        .where(
            EmailTokenORM.user_id == user_id,
            EmailTokenORM.purpose == purpose,
            EmailTokenORM.used_at.is_(None),
        )
        .values(used_at=now)
    )
    row_id = new_id()
    code = _new_verification_code()
    uow.session.add(
        EmailTokenORM(
            id=row_id,
            user_id=user_id,
            purpose=purpose,
            token_hash=_code_digest(row_id, purpose, code, settings),
            expires_at=now + timedelta(minutes=settings.email_code_minutes),
        )
    )
    return code


def _verification_email_body(code: str, settings: Settings) -> str:
    return (
        f"你的邮箱验证码是：{code}\n\n"
        f"请在 {settings.email_code_minutes} 分钟内回到 "
        f"{settings.public_app_url.rstrip('/')}/verify-email 输入这个验证码。\n"
        "如果这不是你的操作，请忽略这封邮件。"
    )


async def _user_view(uow: SqlUnitOfWork, user: UserORM) -> UserView:
    roles = list(
        (
            await uow.session.execute(
                sa.select(UserRoleORM.role).where(UserRoleORM.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    return UserView(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        locale=user.locale,
        verified=user.email_verified_at is not None,
        roles=sorted(roles),
    )


async def _create_session(
    uow: SqlUnitOfWork,
    settings: Settings,
    user: UserORM,
    request: Request,
    response: Response,
) -> None:
    raw_session = opaque_token()
    raw_csrf = opaque_token(24)
    uow.session.add(
        AuthSessionORM(
            id=new_id(),
            user_id=user.id,
            token_hash=token_hash(raw_session, settings.auth_pepper),
            csrf_token_hash=token_hash(raw_csrf, settings.auth_pepper),
            user_agent=request.headers.get("user-agent", "")[:500],
            ip_address=_client_ip(request)[:64],
            expires_at=session_expiry(settings),
        )
    )
    _set_auth_cookies(response, settings, raw_session, raw_csrf)


def _mfa_box(settings: Settings) -> SecretBox:
    try:
        return SecretBox(settings.credential_encryption_key)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="MFA encryption is not configured") from exc


def _recovery_code() -> str:
    raw = secrets.token_hex(5).upper()
    return f"{raw[:5]}-{raw[5:]}"


def _recovery_digest(value: str, settings: Settings) -> str:
    normalized = value.replace("-", "").replace(" ", "").upper()
    return token_hash(normalized, settings.auth_pepper)


def _consume_mfa_code(user: UserORM, code: str, settings: Settings) -> bool:
    recovery = _recovery_digest(code, settings)
    for stored in list(user.mfa_recovery_hashes or []):
        if hmac.compare_digest(recovery, stored):
            user.mfa_recovery_hashes = [item for item in user.mfa_recovery_hashes if item != stored]
            return True
    if not user.mfa_secret_encrypted:
        return False
    secret = _mfa_box(settings).decrypt(user.mfa_secret_encrypted)
    counter = verify_totp(secret, code)
    if counter is None or (user.mfa_last_counter is not None and counter <= user.mfa_last_counter):
        return False
    user.mfa_last_counter = counter
    return True


def _security_audit(
    *,
    actor_id: str | None,
    action: str,
    request: Request,
    details: dict[str, object] | None = None,
) -> AuditLogORM:
    """Create a small, user-visible security event without leaking credentials."""

    return AuditLogORM(
        id=new_id(),
        actor_id=actor_id,
        action=action,
        target_type="user",
        target_id=actor_id,
        request_id=str(getattr(request.state, "request_id", "")),
        details=details or {},
    )


def _affected_rows(result: object) -> int:
    """SQLAlchemy's generic Result type does not expose rowcount statically."""

    return int(getattr(result, "rowcount", 0) or 0)


@router.post("/register", response_model=UserView, status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> UserView:
    await rate_limiter.check(
        f"register:{_client_ip(request)}", 5, 3600, redis_url=settings.redis_url
    )
    email = normalize_email(str(body.email))
    existing = await uow.session.scalar(sa.select(UserORM).where(UserORM.email == email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="email is already registered")
    try:
        encoded = hash_password(body.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    user = UserORM(
        id=new_id(),
        email=email,
        password_hash=encoded,
        display_name=body.display_name.strip(),
        locale=body.locale,
        platform_quota_monthly=await default_monthly_quota(
            uow, UserORM.platform_quota_monthly.default.arg
        ),
    )
    uow.session.add(user)
    # PostgreSQL checks these foreign keys during the flush.  The platform
    # models deliberately do not expose ORM relationships, so SQLAlchemy
    # cannot infer that the user row must be inserted before the role, email
    # token and first session rows.  Make the dependency boundary explicit.
    await uow.session.flush()
    uow.session.add(UserRoleORM(id=new_id(), user_id=user.id, role="player"))
    code = await _issue_email_code(uow, settings, user.id, "verify_email")
    await _create_session(uow, settings, user, request, response)
    await uow.commit()
    await send_email(
        settings, email, "叙界邮箱验证码", _verification_email_body(code, settings)
    )
    return await _user_view(uow, user)


@router.post("/verify-email", response_model=UserView)
async def verify_email(
    body: VerifyEmailRequest,
    request: Request,
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> UserView:
    email = normalize_email(str(body.email))
    await rate_limiter.check(
        f"verify-email:{_client_ip(request)}", 30, 3600, redis_url=settings.redis_url
    )
    await rate_limiter.check(
        f"verify-email-account:{token_hash(email, settings.auth_pepper)}",
        15,
        900,
        redis_url=settings.redis_url,
    )
    user = await uow.session.scalar(sa.select(UserORM).where(UserORM.email == email))
    if user is None:
        raise HTTPException(status_code=400, detail=INVALID_CODE_DETAIL)
    if user.email_verified_at is not None:
        # Re-submitting a code that already did its job — a page reload, a
        # double click, a second tab — is success, not an error.
        return await _user_view(uow, user)
    token = await uow.session.scalar(
        sa.select(EmailTokenORM)
        .where(
            EmailTokenORM.user_id == user.id,
            EmailTokenORM.purpose == "verify_email",
            EmailTokenORM.used_at.is_(None),
            EmailTokenORM.expires_at > datetime.now(UTC),
        )
        .order_by(EmailTokenORM.created_at.desc())
        .with_for_update()
    )
    if token is None:
        raise HTTPException(status_code=400, detail=INVALID_CODE_DETAIL)
    now = datetime.now(UTC)
    if not hmac.compare_digest(
        _code_digest(token.id, "verify_email", body.code, settings), token.token_hash
    ):
        token.attempts += 1
        if token.attempts >= settings.email_code_max_attempts:
            token.used_at = now
        await uow.commit()
        raise HTTPException(status_code=400, detail=INVALID_CODE_DETAIL)
    token.used_at = now
    user.email_verified_at = now
    if user.email in configured_super_admin_emails(settings):
        roles = set(
            (
                await uow.session.scalars(
                    sa.select(UserRoleORM.role).where(UserRoleORM.user_id == user.id)
                )
            ).all()
        )
        added = {"admin", "super_admin"} - roles
        if added:
            uow.session.add_all(
                UserRoleORM(id=new_id(), user_id=user.id, role=role) for role in added
            )
            uow.session.add(
                AuditLogORM(
                    id=new_id(),
                    actor_id=None,
                    action="system.super_admin_bootstrapped",
                    target_type="user",
                    target_id=user.id,
                    request_id=str(getattr(request.state, "request_id", "")),
                    details={"roles_added": sorted(added), "source": "SUPER_ADMIN_EMAILS"},
                )
            )
    await uow.commit()
    return await _user_view(uow, user)


@router.post("/verify-email/resend", status_code=202)
async def resend_verification(
    body: ResendVerificationRequest,
    request: Request,
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, str]:
    await rate_limiter.check(
        f"resend-verification:{_client_ip(request)}", 10, 3600, redis_url=settings.redis_url
    )
    email = normalize_email(str(body.email))
    user = await uow.session.scalar(sa.select(UserORM).where(UserORM.email == email))
    if user is None or user.email_verified_at is not None or user.status != "active":
        return {"status": "accepted"}
    try:
        await rate_limiter.check(
            f"resend-verification-account:{token_hash(email, settings.auth_pepper)}",
            3,
            600,
            redis_url=settings.redis_url,
        )
    except HTTPException:
        # A 429 here would answer "is this address registered?". Swallow it:
        # the limit still holds because no new code is issued or sent.
        return {"status": "accepted"}
    code = await _issue_email_code(uow, settings, user.id, "verify_email")
    await uow.commit()
    await send_email(
        settings, email, "叙界邮箱验证码", _verification_email_body(code, settings)
    )
    return {"status": "accepted"}


@router.post("/login", response_model=UserView)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> UserView:
    ip = _client_ip(request)
    await rate_limiter.check(f"login:{ip}", 10, 900, redis_url=settings.redis_url)
    email = normalize_email(str(body.email))
    await rate_limiter.check(
        f"login-account:{token_hash(email, settings.auth_pepper)}",
        10,
        900,
        redis_url=settings.redis_url,
    )
    user = await uow.session.scalar(sa.select(UserORM).where(UserORM.email == email))
    if user is None or not verify_password(user.password_hash, body.password):
        if user is not None:
            uow.session.add(
                AuditLogORM(
                    id=new_id(), actor_id=user.id, action="auth.login_failed",
                    target_type="user", target_id=user.id,
                    request_id=str(getattr(request.state, "request_id", "")),
                    details={"ip": ip[:64], "user_agent": request.headers.get("user-agent", "")[:200]},
                )
            )
            await uow.commit()
        raise HTTPException(status_code=401, detail="invalid email or password")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="account is not active")
    prior_sessions = (
        await uow.session.execute(
            sa.select(AuthSessionORM.ip_address, AuthSessionORM.user_agent).where(
                AuthSessionORM.user_id == user.id
            ).order_by(AuthSessionORM.created_at.desc()).limit(20)
        )
    ).all()
    current_agent = request.headers.get("user-agent", "")[:500]
    unfamiliar = bool(prior_sessions) and not any(
        prior_ip == ip or (current_agent and prior_agent == current_agent)
        for prior_ip, prior_agent in prior_sessions
    )
    await _create_session(uow, settings, user, request, response)
    if unfamiliar:
        uow.session.add(
            AuditLogORM(
                id=new_id(), actor_id=user.id, action="auth.login_anomaly",
                target_type="user", target_id=user.id,
                request_id=str(getattr(request.state, "request_id", "")),
                details={"ip": ip[:64], "user_agent": current_agent[:200]},
            )
        )
    await uow.commit()
    if unfamiliar:
        await send_email(
            settings,
            user.email,
            "检测到新的登录设备",
            f"时间：{datetime.now(UTC).isoformat()}\nIP：{ip[:64]}\n设备：{current_agent[:200]}\n"
            "如果这不是你的操作，请立即重置密码并撤销其他设备会话。",
        )
    return await _user_view(uow, user)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> Response:
    auth_session = await uow.session.get(AuthSessionORM, principal.auth_session_id)
    if auth_session:
        auth_session.revoked_at = datetime.now(UTC)
        await uow.commit()
    _clear_auth_cookies(response, settings)
    response.status_code = 204
    return response


@router.get("/announcement")
async def announcement(
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """The operator's current notice, if there is one. Public and uncached."""
    return await read_setting(uow, ANNOUNCEMENT_KEY, EMPTY_ANNOUNCEMENT)


@router.get("/me", response_model=UserView)
async def me(
    principal: Annotated[Principal, Depends(current_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> UserView:
    user = await uow.session.get(UserORM, principal.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="account no longer exists")
    return await _user_view(uow, user)


@router.get("/security-events")
async def security_events(
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict[str, object]:
    """A player-readable history of account security changes, not story data."""

    rows = (
        await uow.session.scalars(
            sa.select(AuditLogORM)
            .where(
                AuditLogORM.target_type == "user",
                AuditLogORM.target_id == principal.user_id,
                AuditLogORM.action.like("auth.%"),
            )
            .order_by(AuditLogORM.created_at.desc())
            .limit(limit)
        )
    ).all()
    return {
        "entries": [
            {
                "action": row.action,
                "created_at": row.created_at,
                # The server never returns tokens, recovery codes, raw IPs or
                # user agents here. The small aggregate tells the account
                # owner enough to understand a high-impact security action.
                "sessions_revoked": int((row.details or {}).get("sessions_revoked", 0) or 0),
                "recovery_codes_issued": int(
                    (row.details or {}).get("recovery_codes_issued", 0) or 0
                ),
            }
            for row in rows
        ]
    }


@router.get("/mfa")
async def mfa_status(
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, object]:
    user = await uow.session.get(UserORM, principal.user_id)
    auth_session = await uow.session.get(AuthSessionORM, principal.auth_session_id)
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.mfa_step_up_minutes)
    verified_at = auth_session.mfa_verified_at if auth_session else None
    if verified_at is not None and verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=UTC)
    return {
        "enabled": bool(user and user.mfa_enabled_at),
        "required_for_admin": settings.admin_mfa_required and principal.has_role("admin"),
        "step_up_valid": bool(
            verified_at and verified_at >= cutoff
        ),
        "recovery_codes_remaining": len(user.mfa_recovery_hashes or []) if user else 0,
    }


@router.post("/mfa/enroll")
async def enroll_mfa(
    body: MfaEnrollRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, str]:
    await rate_limiter.check(
        f"mfa-enroll:{principal.user_id}:{_client_ip(request)}", 5, 3600,
        redis_url=settings.redis_url,
    )
    user = await uow.session.get(UserORM, principal.user_id)
    if user is None or not verify_password(user.password_hash, body.password):
        raise HTTPException(status_code=401, detail="password confirmation failed")
    secret = new_totp_secret()
    user.mfa_secret_encrypted = _mfa_box(settings).encrypt(secret)
    user.mfa_enabled_at = None
    user.mfa_recovery_hashes = []
    user.mfa_last_counter = None
    await uow.commit()
    label = quote(user.email, safe="")
    issuer = quote("Narrative Studio", safe="")
    return {
        "secret": secret,
        "otpauth_uri": (
            f"otpauth://totp/{issuer}:{label}?secret={secret}&issuer={issuer}"
            "&algorithm=SHA1&digits=6&period=30"
        ),
    }


@router.post("/mfa/confirm")
async def confirm_mfa(
    body: MfaCodeRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, object]:
    await rate_limiter.check(
        f"mfa-code:{principal.user_id}:{_client_ip(request)}", 10, 600,
        redis_url=settings.redis_url,
    )
    user = await uow.session.scalar(
        sa.select(UserORM).where(UserORM.id == principal.user_id).with_for_update()
    )
    auth_session = await uow.session.get(AuthSessionORM, principal.auth_session_id)
    if user is None or auth_session is None or not user.mfa_secret_encrypted:
        raise HTTPException(status_code=409, detail="MFA enrollment has not started")
    secret = _mfa_box(settings).decrypt(user.mfa_secret_encrypted)
    counter = verify_totp(secret, body.code)
    if counter is None:
        raise HTTPException(status_code=400, detail="MFA code is invalid")
    recovery_codes = [_recovery_code() for _ in range(10)]
    user.mfa_recovery_hashes = [_recovery_digest(code, settings) for code in recovery_codes]
    user.mfa_enabled_at = datetime.now(UTC)
    user.mfa_last_counter = counter
    auth_session.mfa_verified_at = datetime.now(UTC)
    uow.session.add(
        _security_audit(
            actor_id=user.id,
            action="auth.mfa_enabled",
            request=request,
            details={"recovery_codes_issued": len(recovery_codes)},
        )
    )
    await uow.commit()
    return {"enabled": True, "recovery_codes": recovery_codes}


@router.post("/mfa/step-up")
async def step_up_mfa(
    body: MfaCodeRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, object]:
    await rate_limiter.check(
        f"mfa-code:{principal.user_id}:{_client_ip(request)}", 10, 600,
        redis_url=settings.redis_url,
    )
    user = await uow.session.scalar(
        sa.select(UserORM).where(UserORM.id == principal.user_id).with_for_update()
    )
    auth_session = await uow.session.get(AuthSessionORM, principal.auth_session_id)
    if user is None or auth_session is None or user.mfa_enabled_at is None:
        raise HTTPException(status_code=409, detail="MFA is not enabled")
    if not _consume_mfa_code(user, body.code, settings):
        raise HTTPException(status_code=400, detail="MFA code or recovery code is invalid")
    auth_session.mfa_verified_at = datetime.now(UTC)
    await uow.commit()
    return {"verified": True, "valid_for_minutes": settings.mfa_step_up_minutes}


@router.delete("/mfa")
async def disable_mfa(
    body: MfaDisableRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, bool]:
    await rate_limiter.check(
        f"mfa-code:{principal.user_id}:{_client_ip(request)}", 10, 600,
        redis_url=settings.redis_url,
    )
    user = await uow.session.scalar(
        sa.select(UserORM).where(UserORM.id == principal.user_id).with_for_update()
    )
    if user is None or not verify_password(user.password_hash, body.password):
        raise HTTPException(status_code=401, detail="password confirmation failed")
    if user.mfa_enabled_at is None or not _consume_mfa_code(user, body.code, settings):
        raise HTTPException(status_code=400, detail="MFA code or recovery code is invalid")
    user.mfa_secret_encrypted = None
    user.mfa_enabled_at = None
    user.mfa_recovery_hashes = []
    user.mfa_last_counter = None
    await uow.session.execute(
        sa.update(AuthSessionORM)
        .where(AuthSessionORM.user_id == user.id)
        .values(mfa_verified_at=None)
    )
    uow.session.add(
        _security_audit(
            actor_id=user.id,
            action="auth.mfa_disabled",
            request=request,
        )
    )
    await uow.commit()
    return {"disabled": True}


@router.post("/mfa/recovery-codes")
async def rotate_mfa_recovery_codes(
    body: MfaRecoveryCodesRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, object]:
    """Replace every fallback code after proving password and MFA possession."""

    await rate_limiter.check(
        f"mfa-recovery-codes:{principal.user_id}:{_client_ip(request)}",
        5,
        3600,
        redis_url=settings.redis_url,
    )
    user = await uow.session.scalar(
        sa.select(UserORM).where(UserORM.id == principal.user_id).with_for_update()
    )
    auth_session = await uow.session.get(AuthSessionORM, principal.auth_session_id)
    if user is None or auth_session is None or not verify_password(user.password_hash, body.password):
        raise HTTPException(status_code=401, detail="password confirmation failed")
    if user.mfa_enabled_at is None or not _consume_mfa_code(user, body.code, settings):
        raise HTTPException(status_code=400, detail="MFA code or recovery code is invalid")
    recovery_codes = [_recovery_code() for _ in range(10)]
    user.mfa_recovery_hashes = [_recovery_digest(code, settings) for code in recovery_codes]
    auth_session.mfa_verified_at = datetime.now(UTC)
    uow.session.add(
        _security_audit(
            actor_id=user.id,
            action="auth.mfa_recovery_codes_rotated",
            request=request,
            details={"recovery_codes_issued": len(recovery_codes)},
        )
    )
    await uow.commit()
    return {"recovery_codes": recovery_codes}


@router.post("/forgot-password", status_code=202)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, str]:
    await rate_limiter.check(
        f"forgot-password:{_client_ip(request)}", 5, 3600, redis_url=settings.redis_url
    )
    email = normalize_email(str(body.email))
    user = await uow.session.scalar(sa.select(UserORM).where(UserORM.email == email))
    if user is not None and user.status == "active":
        try:
            await rate_limiter.check(
                f"forgot-password-account:{token_hash(email, settings.auth_pepper)}",
                3,
                900,
                redis_url=settings.redis_url,
            )
        except HTTPException:
            # Do not turn a cooldown into an account-enumeration oracle. The
            # caller always sees the same accepted response either way.
            return {"status": "accepted"}
        now = datetime.now(UTC)
        # One recoverable password-reset link at a time is easier to reason
        # about and removes stale inbox links after the user asks again.
        await uow.session.execute(
            sa.update(EmailTokenORM)
            .where(
                EmailTokenORM.user_id == user.id,
                EmailTokenORM.purpose == "reset_password",
                EmailTokenORM.used_at.is_(None),
            )
            .values(used_at=now)
        )
        raw = await _issue_email_token(uow, settings, user.id, "reset_password")
        uow.session.add(
            _security_audit(
                actor_id=user.id,
                action="auth.password_reset_requested",
                request=request,
            )
        )
        await uow.commit()
        url = f"{settings.public_app_url.rstrip('/')}/reset-password?token={raw}"
        await send_email(settings, email, "重置你的叙事世界密码", f"请在有效期内打开：{url}")
    return {"status": "accepted"}


@router.post("/reset-password", status_code=204)
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    response: Response,
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> Response:
    await rate_limiter.check(
        f"reset-password:{_client_ip(request)}", 5, 3600, redis_url=settings.redis_url
    )
    digest = token_hash(body.token, settings.auth_pepper)
    token = await uow.session.scalar(
        sa.select(EmailTokenORM).where(
            EmailTokenORM.token_hash == digest,
            EmailTokenORM.purpose == "reset_password",
            EmailTokenORM.used_at.is_(None),
            EmailTokenORM.expires_at > datetime.now(UTC),
        ).with_for_update()
    )
    if token is None:
        raise HTTPException(status_code=400, detail="reset token is invalid or expired")
    user = await uow.session.get(UserORM, token.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="reset token is invalid")
    try:
        user.password_hash = hash_password(body.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    token.used_at = datetime.now(UTC)
    revoked = await uow.session.execute(
        sa.update(AuthSessionORM)
        .where(AuthSessionORM.user_id == user.id, AuthSessionORM.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    # A concurrent reset link (for example from a duplicate browser tab) must
    # not stay live once the credential has changed.
    await uow.session.execute(
        sa.update(EmailTokenORM)
        .where(
            EmailTokenORM.user_id == user.id,
            EmailTokenORM.purpose == "reset_password",
            EmailTokenORM.used_at.is_(None),
        )
        .values(used_at=datetime.now(UTC))
    )
    uow.session.add(
        _security_audit(
            actor_id=user.id,
            action="auth.password_reset_completed",
            request=request,
            details={"sessions_revoked": _affected_rows(revoked)},
        )
    )
    await uow.commit()
    _clear_auth_cookies(response, settings)
    response.status_code = 204
    return response


@router.post("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> Response:
    """Change a live account password and invalidate every current session.

    A stolen browser session must not be enough to silently replace a password:
    the current password is always required, and MFA-enabled accounts must prove
    possession again.  Signing every device out is deliberate; it creates a
    clean post-change authentication boundary rather than guessing which device
    should still be trusted.
    """

    await rate_limiter.check(
        f"change-password:{principal.user_id}:{_client_ip(request)}",
        5,
        3600,
        redis_url=settings.redis_url,
    )
    user = await uow.session.scalar(
        sa.select(UserORM).where(UserORM.id == principal.user_id).with_for_update()
    )
    auth_session = await uow.session.get(AuthSessionORM, principal.auth_session_id)
    if user is None or auth_session is None or not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status_code=401, detail="password confirmation failed")
    if user.mfa_enabled_at is not None:
        if not body.mfa_code or not _consume_mfa_code(user, body.mfa_code, settings):
            raise HTTPException(status_code=400, detail="MFA code or recovery code is invalid")
        auth_session.mfa_verified_at = datetime.now(UTC)
    if settings.admin_mfa_required and principal.has_role("admin", "super_admin") and user.mfa_enabled_at is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "admin_mfa_enrollment_required",
                "message": "administrator MFA enrollment required",
            },
        )
    try:
        user.password_hash = hash_password(body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    revoked = await uow.session.execute(
        sa.update(AuthSessionORM)
        .where(AuthSessionORM.user_id == user.id, AuthSessionORM.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC), mfa_verified_at=None)
    )
    uow.session.add(
        _security_audit(
            actor_id=user.id,
            action="auth.password_changed",
            request=request,
            details={"sessions_revoked": _affected_rows(revoked)},
        )
    )
    await uow.commit()
    _clear_auth_cookies(response, settings)
    response.status_code = 204
    return response


@router.get("/sessions", response_model=list[SessionView])
async def sessions(
    principal: Annotated[Principal, Depends(current_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> list[SessionView]:
    rows = (
        await uow.session.execute(
            sa.select(AuthSessionORM)
            .where(AuthSessionORM.user_id == principal.user_id, AuthSessionORM.revoked_at.is_(None))
            .order_by(AuthSessionORM.last_seen_at.desc())
        )
    ).scalars().all()
    return [
        SessionView(
            id=row.id,
            user_agent=row.user_agent,
            ip_address=row.ip_address,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            current=row.id == principal.auth_session_id,
        )
        for row in rows
    ]


@router.delete("/sessions", status_code=200)
async def revoke_other_sessions(
    request: Request,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, int]:
    """Keep the current browser while invalidating every other device."""

    revoked = await uow.session.execute(
        sa.update(AuthSessionORM)
        .where(
            AuthSessionORM.user_id == principal.user_id,
            AuthSessionORM.id != principal.auth_session_id,
            AuthSessionORM.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC), mfa_verified_at=None)
    )
    count = _affected_rows(revoked)
    if count:
        uow.session.add(
            _security_audit(
                actor_id=principal.user_id,
                action="auth.other_sessions_revoked",
                request=request,
                details={"sessions_revoked": count},
            )
        )
        await uow.commit()
    return {"revoked": count}


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_csrf)],
    response: Response,
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> Response:
    row = await uow.session.scalar(
        sa.select(AuthSessionORM).where(
            AuthSessionORM.id == session_id, AuthSessionORM.user_id == principal.user_id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    row.revoked_at = datetime.now(UTC)
    row.mfa_verified_at = None
    uow.session.add(
        _security_audit(
            actor_id=principal.user_id,
            action="auth.session_revoked",
            request=request,
            details={"current_session": row.id == principal.auth_session_id},
        )
    )
    await uow.commit()
    if row.id == principal.auth_session_id:
        _clear_auth_cookies(response, settings)
    response.status_code = 204
    return response
