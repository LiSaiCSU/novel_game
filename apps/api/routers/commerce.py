"""Commercial ledger views and high-assurance credit administration.

This router intentionally stops before processor-specific checkout code.  A
real payment channel is allowed to credit a wallet only after verified webhook
delivery has been implemented for the legal entity and region that will sell
the service.  The ledger and order snapshot are therefore safe to build before
choosing Alipay, WeChat Pay, Stripe, or another processor.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from apps.api.billing import BillingPolicy, billing_policy, wallet_available_credits, wallet_balance
from apps.api.deps import settings_dep, uow_dep
from apps.api.notifications import add_notification
from apps.api.platform_settings import read_setting, write_setting
from apps.api.rate_limit import rate_limiter
from apps.api.security import Principal, require_role_csrf, require_roles, verified_principal
from apps.api.tenancy import set_tenant_context
from database.models.platform import (
    AuditLogORM,
    CreditCampaignORM,
    PaymentOrderORM,
    UserORM,
    WalletHoldORM,
    WalletLedgerORM,
)
from database.repositories.sql import SqlUnitOfWork
from engine.core.config import Settings
from engine.core.ids import new_id

router = APIRouter(prefix="/commerce", tags=["v1-commerce"])
admin_router = APIRouter(prefix="/admin/commerce", tags=["v1-admin-commerce"])

COMMERCE_CATALOG_KEY = "commerce_catalog"
DEFAULT_COMMERCE_CATALOG: dict[str, object] = {"currency": "CNY", "items": []}
_CATALOG_CODE = re.compile(r"[a-z][a-z0-9_-]{1,47}")


class CommerceCatalogItem(BaseModel):
    """A display-only credit package until a payment processor is approved."""

    code: str = Field(min_length=2, max_length=48)
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)
    credits: int = Field(ge=1, le=10_000_000_000)
    price_minor: int = Field(ge=1, le=10_000_000_000)
    badge: str = Field(default="", max_length=36)
    sort_order: int = Field(default=0, ge=0, le=10_000)
    active: bool = True

    @field_validator("code")
    @classmethod
    def normalized_code(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _CATALOG_CODE.fullmatch(normalized):
            raise ValueError("package code must be a lowercase URL-safe identifier")
        return normalized

    @field_validator("name", "description", "badge")
    @classmethod
    def trim_display_text(cls, value: str) -> str:
        return value.strip()


class CommerceCatalog(BaseModel):
    currency: str = Field(default="CNY", min_length=3, max_length=3)
    items: list[CommerceCatalogItem] = Field(default_factory=list, max_length=24)

    @field_validator("currency")
    @classmethod
    def normalized_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", normalized):
            raise ValueError("currency must be an ISO 4217 alphabetic code")
        return normalized

    @model_validator(mode="after")
    def packages_have_unique_codes(self) -> CommerceCatalog:
        codes = [item.code for item in self.items]
        if len(codes) != len(set(codes)):
            raise ValueError("package codes must be unique")
        return self

    def public_view(self, *, active_only: bool) -> dict[str, object]:
        items = [item for item in self.items if item.active] if active_only else self.items
        return {
            "currency": self.currency,
            "items": [item.model_dump() for item in sorted(items, key=lambda item: (item.sort_order, item.code))],
            # The display catalog must never be mistaken for a checkout API.
            "checkout_live": False,
        }


class CommerceCatalogWrite(CommerceCatalog):
    reason: str = Field(min_length=3, max_length=500)

    def catalog(self) -> CommerceCatalog:
        return CommerceCatalog(currency=self.currency, items=self.items)


class CreditCampaignCreateWrite(BaseModel):
    code: str = Field(min_length=2, max_length=48)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    credit_amount: int = Field(ge=1, le=10_000_000_000)
    status: Literal["draft", "active", "paused"] = "draft"
    starts_at: datetime
    ends_at: datetime
    max_redemptions: int | None = Field(default=None, ge=1, le=10_000_000)
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("code")
    @classmethod
    def normalized_code(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _CATALOG_CODE.fullmatch(normalized):
            raise ValueError("campaign code must be a lowercase URL-safe identifier")
        return normalized

    @field_validator("name", "description")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def has_a_valid_window(self) -> CreditCampaignCreateWrite:
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("campaign times must include a timezone")
        if self.ends_at <= self.starts_at:
            raise ValueError("campaign end must be after its start")
        return self


class CreditCampaignStatusWrite(BaseModel):
    status: Literal["draft", "active", "paused", "ended"]
    reason: str = Field(min_length=3, max_length=500)


class WalletAdjustmentWrite(BaseModel):
    credit_delta: int = Field(ge=-10_000_000_000, le=10_000_000_000)
    reason: str = Field(min_length=3, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=120)
    entry_type: Literal["grant", "adjustment", "refund", "reversal"] = "adjustment"

    @model_validator(mode="after")
    def delta_must_not_be_zero(self) -> WalletAdjustmentWrite:
        if self.credit_delta == 0:
            raise ValueError("credit_delta must not be zero")
        return self


class BillingPolicyWrite(BaseModel):
    """A disclosed turn-billing policy, protected by admin MFA and CSRF."""

    mode: Literal["disabled", "wallet"] = "disabled"
    credit_label: str = Field(default="叙点", min_length=1, max_length=24)
    cost_microunits_per_credit: int = Field(default=10_000, ge=1, le=10_000_000_000)
    turn_reserve_credits: int = Field(default=100, ge=1, le=10_000_000_000)
    hold_minutes: int = Field(default=20, ge=1, le=120)
    reason: str = Field(min_length=3, max_length=500)

    def policy(self) -> BillingPolicy:
        return BillingPolicy.from_value(self.model_dump(exclude={"reason"}))


async def commerce_catalog(uow: SqlUnitOfWork) -> CommerceCatalog:
    """Load a defensive catalog: a malformed setting can never expose checkout."""

    raw = await read_setting(uow, COMMERCE_CATALOG_KEY, DEFAULT_COMMERCE_CATALOG)
    try:
        return CommerceCatalog.model_validate(raw)
    except ValidationError:
        return CommerceCatalog()


def _as_utc(value: datetime) -> datetime:
    """Make SQLite's timezone-naive development values safe to compare."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _campaign_view(
    campaign: CreditCampaignORM,
    *,
    now: datetime | None = None,
    include_claimable: bool = True,
) -> dict[str, object]:
    now = now or datetime.now(UTC)
    starts_at = _as_utc(campaign.starts_at)
    ends_at = _as_utc(campaign.ends_at)
    remaining = (
        None
        if campaign.max_redemptions is None
        else max(0, campaign.max_redemptions - campaign.redemption_count)
    )
    payload: dict[str, object] = {
        "id": campaign.id,
        "code": campaign.code,
        "name": campaign.name,
        "description": campaign.description,
        "credit_amount": campaign.credit_amount,
        "status": campaign.status,
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "max_redemptions": campaign.max_redemptions,
        "redemption_count": campaign.redemption_count,
        "redemptions_remaining": remaining,
    }
    if include_claimable:
        payload["claimable"] = (
            campaign.status == "active"
            and starts_at <= now < ends_at
            and (remaining is None or remaining > 0)
        )
    return payload


def _entry_view(entry: WalletLedgerORM) -> dict[str, object]:
    return {
        "id": entry.id,
        "credit_delta": entry.credit_delta,
        "entry_type": entry.entry_type,
        "source_type": entry.source_type,
        "source_id": entry.source_id,
        "reason": entry.reason,
        "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
        "created_at": entry.created_at.isoformat(),
    }


async def _wallet_view(
    uow: SqlUnitOfWork, user_id: str, *, limit: int, offset: int
) -> dict[str, object]:
    policy = await billing_policy(uow)
    total = await wallet_balance(uow, user_id)
    available = await wallet_available_credits(uow, user_id)
    count = int(
        await uow.session.scalar(
            sa.select(sa.func.count()).select_from(WalletLedgerORM).where(WalletLedgerORM.user_id == user_id)
        )
        or 0
    )
    rows = (
        await uow.session.scalars(
            sa.select(WalletLedgerORM)
            .where(WalletLedgerORM.user_id == user_id)
            .order_by(WalletLedgerORM.created_at.desc(), WalletLedgerORM.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return {
        "credit_label": policy.credit_label,
        "balance": total,
        "available_balance": available,
        "reserved_credits": total - available,
        "billing_policy": policy.public_view(),
        "entries": [_entry_view(entry) for entry in rows],
        "total": count,
        "limit": limit,
        "offset": offset,
    }


@router.get("/wallet")
async def wallet(
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    return await _wallet_view(uow, principal.user_id, limit=limit, offset=offset)


@router.get("/billing-policy")
async def player_billing_policy(
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Pricing mechanics visible to a signed-in player before an action runs."""

    await set_tenant_context(uow.session, principal.user_id)
    return (await billing_policy(uow)).public_view()


@router.get("/catalog")
async def player_catalog(
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Public package prices, deliberately without an order or payment action.

    Publishing prices before sign-in lets players evaluate the value proposition
    without creating an account.  A processor-specific checkout remains absent
    until the selling entity, region, refunds and signed webhooks are approved.
    """

    return (await commerce_catalog(uow)).public_view(active_only=True)


@router.get("/campaigns")
async def player_campaigns(
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Return only campaigns a player can safely be offered right now."""

    await set_tenant_context(uow.session, principal.user_id)
    now = datetime.now(UTC)
    campaigns = (
        await uow.session.scalars(
            sa.select(CreditCampaignORM)
            .where(
                CreditCampaignORM.status == "active",
                CreditCampaignORM.starts_at <= now,
                CreditCampaignORM.ends_at > now,
            )
            .order_by(CreditCampaignORM.ends_at.asc(), CreditCampaignORM.created_at.desc())
        )
    ).all()
    return {
        "credit_label": (await billing_policy(uow)).credit_label,
        "items": [
            _campaign_view(campaign, now=now)
            for campaign in campaigns
            if campaign.max_redemptions is None or campaign.redemption_count < campaign.max_redemptions
        ],
    }


@router.post("/campaigns/{code}/redeem")
async def redeem_campaign(
    code: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("player", "creator", "reviewer", "admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, object]:
    """Grant a campaign only once per player, as a normal ledger entry.

    The campaign-row lock serializes claims against a shared cap. The wallet
    idempotency key also makes retried browser requests harmless.
    """

    normalized_code = code.strip().lower()
    if not _CATALOG_CODE.fullmatch(normalized_code):
        raise HTTPException(status_code=404, detail="campaign unavailable")
    await set_tenant_context(uow.session, principal.user_id)
    await rate_limiter.check(
        f"campaign-redeem:{principal.user_id}", 12, 3600, redis_url=settings.redis_url
    )
    now = datetime.now(UTC)
    campaign = await uow.session.scalar(
        sa.select(CreditCampaignORM)
        .where(CreditCampaignORM.code == normalized_code)
        .with_for_update()
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign unavailable")
    if (
        campaign.status != "active"
        or _as_utc(campaign.starts_at) > now
        or _as_utc(campaign.ends_at) <= now
    ):
        raise HTTPException(status_code=409, detail="campaign is not currently claimable")

    idempotency_key = f"campaign:{campaign.id}:{principal.user_id}"
    existing = await uow.session.scalar(
        sa.select(WalletLedgerORM).where(
            WalletLedgerORM.user_id == principal.user_id,
            WalletLedgerORM.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return {
            "idempotent_replay": True,
            "campaign": _campaign_view(campaign, now=now),
            **_entry_view(existing),
            "balance": await wallet_balance(uow, principal.user_id),
            "available_balance": await wallet_available_credits(uow, principal.user_id),
        }
    if (
        campaign.max_redemptions is not None
        and campaign.redemption_count >= campaign.max_redemptions
    ):
        raise HTTPException(status_code=409, detail="campaign redemption limit reached")

    before = await wallet_balance(uow, principal.user_id)
    entry = WalletLedgerORM(
        id=new_id(),
        user_id=principal.user_id,
        credit_delta=campaign.credit_amount,
        entry_type="grant",
        source_type="campaign",
        source_id=campaign.id,
        idempotency_key=idempotency_key,
        actor_id=None,
        reason=campaign.name,
        entry_metadata={"campaign_code": campaign.code, "campaign_name": campaign.name},
    )
    campaign.redemption_count += 1
    uow.session.add(entry)
    add_notification(
        uow.session,
        user_id=principal.user_id,
        kind="campaign.redeemed",
        title="活动权益已到账",
        body=f"{campaign.name}：+{campaign.credit_amount}",
        href="/wallet",
    )
    uow.session.add(
        AuditLogORM(
            id=new_id(),
            actor_id=principal.user_id,
            action="commerce.campaign_redeemed",
            target_type="campaign",
            target_id=campaign.id,
            request_id=str(getattr(request.state, "request_id", "")),
            details={"code": campaign.code, "credit_amount": campaign.credit_amount},
        )
    )
    await uow.commit()
    return {
        "idempotent_replay": False,
        "campaign": _campaign_view(campaign, now=now),
        **_entry_view(entry),
        "balance": before + campaign.credit_amount,
        "available_balance": await wallet_available_credits(uow, principal.user_id),
    }


@admin_router.get("/summary")
async def commerce_summary(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Revenue-adjacent facts, intentionally excluding player identity and prose."""

    await set_tenant_context(uow.session, principal.user_id)
    granted = sa.func.coalesce(
        sa.func.sum(sa.case((WalletLedgerORM.credit_delta > 0, WalletLedgerORM.credit_delta), else_=0)), 0
    )
    spent = sa.func.coalesce(
        sa.func.sum(sa.case((WalletLedgerORM.credit_delta < 0, -WalletLedgerORM.credit_delta), else_=0)), 0
    )
    since = datetime.now(UTC) - timedelta(days=30)
    aggregate = (
        await uow.session.execute(
            sa.select(
                sa.func.count(sa.distinct(WalletLedgerORM.user_id)),
                granted,
                spent,
                sa.func.count(),
                sa.func.coalesce(
                    sa.func.sum(
                        sa.case(
                            (WalletLedgerORM.created_at >= since, WalletLedgerORM.credit_delta),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
        )
    ).one()
    order_counts = (
        await uow.session.execute(
            sa.select(PaymentOrderORM.status, sa.func.count())
            .group_by(PaymentOrderORM.status)
            .order_by(PaymentOrderORM.status)
        )
    ).all()
    now = datetime.now(UTC)
    hold_aggregate = (
        await uow.session.execute(
            sa.select(
                sa.func.count(),
                sa.func.coalesce(sa.func.sum(WalletHoldORM.reserved_credits), 0),
            ).where(WalletHoldORM.status == "held", WalletHoldORM.expires_at > now)
        )
    ).one()
    policy = await billing_policy(uow)
    catalog = await commerce_catalog(uow)
    campaign_counts = (
        await uow.session.execute(
            sa.select(CreditCampaignORM.status, sa.func.count())
            .group_by(CreditCampaignORM.status)
            .order_by(CreditCampaignORM.status)
        )
    ).all()
    return {
        "credit_label": policy.credit_label,
        "wallet_accounts": int(aggregate[0] or 0),
        "credits_issued": int(aggregate[1] or 0),
        "credits_settled": int(aggregate[2] or 0),
        "credits_outstanding": int(aggregate[1] or 0) - int(aggregate[2] or 0),
        "active_holds": int(hold_aggregate[0] or 0),
        "credits_reserved": int(hold_aggregate[1] or 0),
        "ledger_entries": int(aggregate[3] or 0),
        "net_credit_delta_30d": int(aggregate[4] or 0),
        "orders_by_status": {str(status): int(count) for status, count in order_counts},
        "checkout_live": False,
        "billing_policy": policy.public_view(),
        "catalog_packages": len(catalog.items),
        "catalog_active_packages": sum(1 for item in catalog.items if item.active),
        "campaigns_by_status": {str(status): int(count) for status, count in campaign_counts},
    }


@admin_router.get("/billing-policy")
async def admin_billing_policy(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    return (await billing_policy(uow)).public_view()


@admin_router.get("/catalog")
async def admin_catalog(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Show inactive packages too, so operators can prepare a launch safely."""

    await set_tenant_context(uow.session, principal.user_id)
    return (await commerce_catalog(uow)).public_view(active_only=False)


@admin_router.get("/campaigns")
async def admin_campaigns(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """List draft, paused and completed campaigns for accountable operations."""

    await set_tenant_context(uow.session, principal.user_id)
    now = datetime.now(UTC)
    rows = (
        await uow.session.scalars(
            sa.select(CreditCampaignORM).order_by(
                CreditCampaignORM.created_at.desc(), CreditCampaignORM.code.asc()
            )
        )
    ).all()
    return {
        "credit_label": (await billing_policy(uow)).credit_label,
        "items": [_campaign_view(campaign, now=now) for campaign in rows],
    }


@admin_router.post("/campaigns")
async def create_campaign(
    body: CreditCampaignCreateWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Prepare a bounded campaign; activation remains an audited choice."""

    await set_tenant_context(uow.session, principal.user_id)
    existing = await uow.session.scalar(
        sa.select(CreditCampaignORM.id).where(CreditCampaignORM.code == body.code)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="campaign code already exists")
    campaign = CreditCampaignORM(
        id=new_id(),
        code=body.code,
        name=body.name,
        description=body.description,
        credit_amount=body.credit_amount,
        status=body.status,
        starts_at=_as_utc(body.starts_at),
        ends_at=_as_utc(body.ends_at),
        max_redemptions=body.max_redemptions,
        redemption_count=0,
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    uow.session.add(campaign)
    uow.session.add(
        AuditLogORM(
            id=new_id(),
            actor_id=principal.user_id,
            action="commerce.campaign_created",
            target_type="campaign",
            target_id=campaign.id,
            request_id=str(getattr(request.state, "request_id", "")),
            details={
                "code": campaign.code,
                "credit_amount": campaign.credit_amount,
                "status": campaign.status,
                "starts_at": _as_utc(campaign.starts_at).isoformat(),
                "ends_at": _as_utc(campaign.ends_at).isoformat(),
                "max_redemptions": campaign.max_redemptions,
                "reason": body.reason.strip(),
            },
        )
    )
    await uow.commit()
    return _campaign_view(campaign)


@admin_router.put("/campaigns/{campaign_id}/status")
async def set_campaign_status(
    campaign_id: str,
    body: CreditCampaignStatusWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Pause or end a campaign without deleting its financial evidence."""

    await set_tenant_context(uow.session, principal.user_id)
    campaign = await uow.session.scalar(
        sa.select(CreditCampaignORM)
        .where(CreditCampaignORM.id == campaign_id)
        .with_for_update()
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    now = datetime.now(UTC)
    if campaign.status == "ended" and body.status != "ended":
        raise HTTPException(status_code=409, detail="an ended campaign cannot be reactivated")
    if body.status == "active" and _as_utc(campaign.ends_at) <= now:
        raise HTTPException(status_code=409, detail="an expired campaign cannot be reactivated")
    previous = campaign.status
    campaign.status = body.status
    campaign.updated_by = principal.user_id
    uow.session.add(
        AuditLogORM(
            id=new_id(),
            actor_id=principal.user_id,
            action="commerce.campaign_status_changed",
            target_type="campaign",
            target_id=campaign.id,
            request_id=str(getattr(request.state, "request_id", "")),
            details={"code": campaign.code, "from": previous, "to": body.status, "reason": body.reason.strip()},
        )
    )
    await uow.commit()
    return _campaign_view(campaign, now=now)


@admin_router.put("/catalog")
async def set_catalog(
    body: CommerceCatalogWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Persist the display catalog with a reasoned, immutable operator audit."""

    await set_tenant_context(uow.session, principal.user_id)
    catalog = body.catalog()
    payload = catalog.public_view(active_only=False)
    await write_setting(uow, principal.user_id, COMMERCE_CATALOG_KEY, payload)
    uow.session.add(
        AuditLogORM(
            id=new_id(),
            actor_id=principal.user_id,
            action="commerce.catalog_changed",
            target_type="platform",
            target_id=COMMERCE_CATALOG_KEY,
            request_id=str(getattr(request.state, "request_id", "")),
            details={
                "currency": catalog.currency,
                "packages": [item.model_dump() for item in catalog.items],
                "reason": body.reason.strip(),
            },
        )
    )
    await uow.commit()
    return payload


@admin_router.put("/billing-policy")
async def set_billing_policy(
    body: BillingPolicyWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Enable/disable platform turn billing with a durable operator audit."""

    await set_tenant_context(uow.session, principal.user_id)
    policy = body.policy()
    payload = policy.public_view()
    await write_setting(uow, principal.user_id, "commerce_billing_policy", payload)
    uow.session.add(
        AuditLogORM(
            id=new_id(),
            actor_id=principal.user_id,
            action="commerce.billing_policy_changed",
            target_type="platform",
            target_id="commerce_billing_policy",
            request_id=str(getattr(request.state, "request_id", "")),
            details={**payload, "reason": body.reason.strip()},
        )
    )
    await uow.commit()
    return payload


@admin_router.get("/users/{user_id}/wallet")
async def admin_wallet(
    user_id: str,
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    user = await uow.session.get(UserORM, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return {"user_id": user.id, "email": user.email, **await _wallet_view(uow, user.id, limit=limit, offset=offset)}


@admin_router.post("/users/{user_id}/adjustments")
async def adjust_wallet(
    user_id: str,
    body: WalletAdjustmentWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Create a traceable correction without ever editing financial history."""

    await set_tenant_context(uow.session, principal.user_id)
    # Every debit path must take this same lock before calculating balance.  It
    # prevents two privileged corrections from independently over-drawing one
    # wallet in PostgreSQL; SQLite safely serializes writes in development.
    user = await uow.session.scalar(
        sa.select(UserORM).where(UserORM.id == user_id).with_for_update()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if user.status == "deleted":
        raise HTTPException(status_code=409, detail="account no longer exists")

    existing = await uow.session.scalar(
        sa.select(WalletLedgerORM).where(
            WalletLedgerORM.user_id == user_id,
            WalletLedgerORM.idempotency_key == body.idempotency_key,
        )
    )
    if existing is not None:
        if existing.credit_delta != body.credit_delta or existing.reason != body.reason:
            raise HTTPException(status_code=409, detail="idempotency key was already used")
        return {
            "idempotent_replay": True,
            **_entry_view(existing),
            "balance": await wallet_balance(uow, user_id),
            "available_balance": await wallet_available_credits(uow, user_id),
        }

    before = await wallet_balance(uow, user_id)
    available_before = await wallet_available_credits(uow, user_id)
    after = before + body.credit_delta
    if after < 0 or available_before + body.credit_delta < 0:
        raise HTTPException(
            status_code=409,
            detail="wallet balance cannot become negative or consume active turn reservations",
        )
    entry = WalletLedgerORM(
        id=new_id(),
        user_id=user_id,
        credit_delta=body.credit_delta,
        entry_type=body.entry_type,
        source_type="admin_adjustment",
        source_id=None,
        idempotency_key=body.idempotency_key,
        actor_id=principal.user_id,
        reason=body.reason.strip(),
        entry_metadata={
            "channel": "admin",
            "before": before,
            "after": after,
            "available_before": available_before,
            "available_after": available_before + body.credit_delta,
        },
    )
    uow.session.add(entry)
    uow.session.add(
        AuditLogORM(
            id=new_id(),
            actor_id=principal.user_id,
            action="wallet.adjustment",
            target_type="user",
            target_id=user_id,
            request_id=str(getattr(request.state, "request_id", "")),
            details={
                "credit_delta": body.credit_delta,
                "entry_type": body.entry_type,
                "before": before,
                "after": after,
                "available_before": available_before,
                "available_after": available_before + body.credit_delta,
                "reason": body.reason.strip(),
            },
        )
    )
    await uow.commit()
    return {
        "idempotent_replay": False,
        **_entry_view(entry),
        "balance": after,
        "available_balance": available_before + body.credit_delta,
    }
