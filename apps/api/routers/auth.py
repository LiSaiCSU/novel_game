"""Public email/password authentication API."""

from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import quote

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field

from apps.api.deps import settings_dep, uow_dep
from apps.api.emailer import send_email
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


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(TokenRequest):
    password: str = Field(min_length=12, max_length=256)


class MfaEnrollRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class MfaDisableRequest(MfaCodeRequest):
    password: str = Field(min_length=1, max_length=256)


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
    )
    uow.session.add(user)
    # PostgreSQL checks these foreign keys during the flush.  The platform
    # models deliberately do not expose ORM relationships, so SQLAlchemy
    # cannot infer that the user row must be inserted before the role, email
    # token and first session rows.  Make the dependency boundary explicit.
    await uow.session.flush()
    uow.session.add(UserRoleORM(id=new_id(), user_id=user.id, role="player"))
    raw = await _issue_email_token(uow, settings, user.id, "verify_email")
    await _create_session(uow, settings, user, request, response)
    await uow.commit()
    url = f"{settings.public_app_url.rstrip('/')}/verify-email?token={raw}"
    await send_email(settings, email, "验证你的叙事世界账号", f"请在有效期内打开：{url}")
    return await _user_view(uow, user)


@router.post("/verify-email", response_model=UserView)
async def verify_email(
    body: TokenRequest,
    request: Request,
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> UserView:
    await rate_limiter.check(
        f"verify-email:{_client_ip(request)}", 10, 3600, redis_url=settings.redis_url
    )
    digest = token_hash(body.token, settings.auth_pepper)
    token = await uow.session.scalar(
        sa.select(EmailTokenORM).where(
            EmailTokenORM.token_hash == digest,
            EmailTokenORM.purpose == "verify_email",
            EmailTokenORM.used_at.is_(None),
            EmailTokenORM.expires_at > datetime.now(UTC),
        )
    )
    if token is None:
        raise HTTPException(status_code=400, detail="verification token is invalid or expired")
    user = await uow.session.get(UserORM, token.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="verification token is invalid")
    token.used_at = datetime.now(UTC)
    user.email_verified_at = datetime.now(UTC)
    await uow.commit()
    return await _user_view(uow, user)


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


@router.get("/me", response_model=UserView)
async def me(
    principal: Annotated[Principal, Depends(current_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> UserView:
    user = await uow.session.get(UserORM, principal.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="account no longer exists")
    return await _user_view(uow, user)


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
    await uow.commit()
    return {"disabled": True}


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
    if user is not None:
        raw = await _issue_email_token(uow, settings, user.id, "reset_password")
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
        )
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
    await uow.session.execute(
        sa.update(AuthSessionORM)
        .where(AuthSessionORM.user_id == user.id, AuthSessionORM.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
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


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: str,
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
    await uow.commit()
    if row.id == principal.auth_session_id:
        _clear_auth_cookies(response, settings)
    response.status_code = 204
    return response
