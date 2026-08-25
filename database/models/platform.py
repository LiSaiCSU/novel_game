"""Account, tenancy, creator and immutable-release persistence models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, JSONType, TimestampMixin, utcnow


class UserORM(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    email: Mapped[str] = mapped_column(sa.String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(sa.Text)
    display_name: Mapped[str] = mapped_column(sa.String(80), default="")
    locale: Mapped[str] = mapped_column(sa.String(20), default="zh-CN")
    email_verified_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(sa.String(32), default="active", index=True)
    delete_after: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    platform_quota_monthly: Mapped[int] = mapped_column(sa.Integer, default=200_000)
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    mfa_recovery_hashes: Mapped[list[str]] = mapped_column(JSONType, default=list)
    mfa_last_counter: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    analytics_consent: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    analytics_consent_updated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    user_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class UserRoleORM(Base):
    __tablename__ = "user_roles"
    __table_args__ = (sa.UniqueConstraint("user_id", "role", name="uq_user_role"),)
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(sa.String(32), default="player", index=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class AuthSessionORM(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    csrf_token_hash: Mapped[str] = mapped_column(sa.String(64))
    user_agent: Mapped[str] = mapped_column(sa.String(500), default="")
    ip_address: Mapped[str] = mapped_column(sa.String(64), default="")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    mfa_verified_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class EmailTokenORM(Base):
    __tablename__ = "email_tokens"
    __table_args__ = (sa.Index("idx_email_tokens_user_purpose", "user_id", "purpose", "used_at"),)
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(sa.String(32))
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    # Short numeric codes need a per-row lockout; the rate limiter alone only
    # bounds the guess rate, not the total guesses against one live code.
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")


class ProjectORM(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (sa.UniqueConstraint("owner_id", "slug", name="uq_project_owner_slug"),)
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(sa.String(100), index=True)
    title: Mapped[str] = mapped_column(sa.String(120))
    summary: Mapped[str] = mapped_column(sa.Text, default="")
    locale: Mapped[str] = mapped_column(sa.String(20), default="zh-CN")
    rating: Mapped[str] = mapped_column(sa.String(16), default="16+")
    status: Mapped[str] = mapped_column(sa.String(32), default="draft", index=True)
    current_revision: Mapped[int] = mapped_column(sa.Integer, default=0)
    share_token_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, unique=True)
    project_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class ProjectRevisionORM(Base):
    __tablename__ = "project_revisions"
    __table_args__ = (sa.UniqueConstraint("project_id", "revision", name="uq_project_revision"),)
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("users.id"), index=True)
    revision: Mapped[int] = mapped_column(sa.Integer)
    document: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    diagnostics: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class ContentReleaseORM(TimestampMixin, Base):
    __tablename__ = "content_releases"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "version", name="uq_release_project_version"),
    )
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    revision_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("project_revisions.id"), index=True
    )
    owner_id: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("users.id"), index=True)
    version: Mapped[str] = mapped_column(sa.String(40))
    # A digest identifies content, not ownership. Different creators may
    # legitimately publish byte-identical packages and share the cache entry.
    checksum: Mapped[str] = mapped_column(sa.String(64), index=True)
    title: Mapped[str] = mapped_column(sa.String(120))
    summary: Mapped[str] = mapped_column(sa.Text, default="")
    locale: Mapped[str] = mapped_column(sa.String(20), default="zh-CN", index=True)
    rating: Mapped[str] = mapped_column(sa.String(16), default="16+", index=True)
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    visibility: Mapped[str] = mapped_column(sa.String(24), default="private", index=True)
    moderation_status: Mapped[str] = mapped_column(sa.String(32), default="draft", index=True)
    share_token_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    artifact: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class AssetORM(TimestampMixin, Base):
    __tablename__ = "assets"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "logical_key", name="uq_project_asset_key"),
    )
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(sa.String(24))
    logical_key: Mapped[str] = mapped_column(sa.String(80), default="")
    object_key: Mapped[str] = mapped_column(sa.String(500), unique=True)
    content_type: Mapped[str] = mapped_column(sa.String(100))
    byte_size: Mapped[int] = mapped_column(sa.BigInteger)
    checksum: Mapped[str] = mapped_column(sa.String(64), index=True)
    width: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    thumbnail_object_key: Mapped[str | None] = mapped_column(
        sa.String(500), nullable=True, unique=True
    )
    thumbnail_width: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    thumbnail_height: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    alt_text: Mapped[str] = mapped_column(sa.String(300), default="")
    status: Mapped[str] = mapped_column(sa.String(24), default="pending")


class PlaythroughORM(TimestampMixin, Base):
    __tablename__ = "playthroughs"
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    release_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("content_releases.id"), index=True
    )
    scenario_key: Mapped[str] = mapped_column(sa.String(80))
    world_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, unique=True)
    game_session_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(sa.String(120), default="")
    status: Mapped[str] = mapped_column(sa.String(24), default="active", index=True)
    ending_key: Mapped[str | None] = mapped_column(sa.String(80), nullable=True)
    ending_title: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    is_preview: Mapped[bool] = mapped_column(sa.Boolean, default=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    player_config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class LlmCredentialORM(TimestampMixin, Base):
    __tablename__ = "llm_credentials"
    __table_args__ = (sa.UniqueConstraint("user_id", "provider", name="uq_user_provider_key"),)
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(sa.String(60))
    default_model: Mapped[str] = mapped_column(sa.String(160), default="")
    base_url: Mapped[str] = mapped_column(sa.String(500), default="")
    encrypted_secret: Mapped[str] = mapped_column(sa.Text)
    key_hint: Mapped[str] = mapped_column(sa.String(16), default="")
    status: Mapped[str] = mapped_column(sa.String(24), default="active")


class PlatformSettingORM(TimestampMixin, Base):
    """Deployment-wide switches an administrator can change without a deploy.

    One row per setting rather than one column per setting: the set of things
    an operator needs to reach at runtime grows, and a schema migration is a
    poor answer to "turn the site read-only for twenty minutes".
    """

    __tablename__ = "platform_settings"
    key: Mapped[str] = mapped_column(sa.String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    updated_by: Mapped[str] = mapped_column(sa.String(36), default="")


class PlatformLlmConfigORM(TimestampMixin, Base):
    """Encrypted connection plus narrative/reasoning model profiles."""

    __tablename__ = "platform_llm_config"
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    provider: Mapped[str] = mapped_column(sa.String(60), default="null")
    model: Mapped[str] = mapped_column(sa.String(160), default="")
    base_url: Mapped[str] = mapped_column(sa.String(500), default="")
    encrypted_secret: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    key_hint: Mapped[str] = mapped_column(sa.String(16), default="")
    # ``model`` and ``extra_body`` remain the narrative profile so existing
    # installations and API clients keep their meaning after the split.
    extra_body: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    reasoning_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    reasoning_model: Mapped[str] = mapped_column(sa.String(160), default="")
    reasoning_extra_body: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    updated_by: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class PlatformLlmEndpointORM(TimestampMixin, Base):
    """One reachable model endpoint in the platform's ordered failover chain.

    The older single-row ``platform_llm_config`` could only describe one way to
    reach a model, so a bad key or a gateway outage took the whole platform
    down. Each row here is an independent connection with its own credential
    and its own model names, and ``priority`` decides the order they are tried.
    """

    __tablename__ = "platform_llm_endpoints"
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(80), default="")
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    #: Lower is preferred. Ties break on ``name`` so ordering stays stable.
    priority: Mapped[int] = mapped_column(sa.Integer, default=100, index=True)
    provider: Mapped[str] = mapped_column(sa.String(60), default="compatible")
    base_url: Mapped[str] = mapped_column(sa.String(500), default="")
    encrypted_secret: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    key_hint: Mapped[str] = mapped_column(sa.String(16), default="")
    narrative_model: Mapped[str] = mapped_column(sa.String(160), default="")
    reasoning_model: Mapped[str] = mapped_column(sa.String(160), default="")
    narrative_extra_body: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    reasoning_extra_body: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    #: Health, written by the turn path so operators can see reality rather
    #: than the last manual test result.
    last_ok_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str] = mapped_column(sa.String(200), default="")
    consecutive_failures: Mapped[int] = mapped_column(sa.Integer, default=0)
    updated_by: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class UsageLedgerORM(Base):
    __tablename__ = "usage_ledger"
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("users.id"), index=True)
    playthrough_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(sa.String(60), default="")
    model: Mapped[str] = mapped_column(sa.String(120), default="")
    input_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    cost_microunits: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    success: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, index=True
    )


class WalletLedgerORM(Base):
    """Append-only player credit ledger.

    ``credit_delta`` is deliberately not cached on ``users``.  A balance is a
    derived value, which means an operator can never silently overwrite a
    player's financial history.  Reversals are represented by a new entry,
    never a mutation or deletion of the original entry.
    """

    __tablename__ = "wallet_ledger"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_wallet_ledger_idempotency"),
        sa.CheckConstraint("credit_delta <> 0", name="ck_wallet_ledger_nonzero_delta"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    #: Positive values grant narrative credits; negative values settle usage,
    #: refunds, chargebacks or a documented administrative correction.
    credit_delta: Mapped[int] = mapped_column(sa.BigInteger)
    entry_type: Mapped[str] = mapped_column(sa.String(32), index=True)
    source_type: Mapped[str] = mapped_column(sa.String(40), default="")
    source_id: Mapped[str | None] = mapped_column(sa.String(120), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(sa.String(120))
    actor_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reason: Mapped[str] = mapped_column(sa.Text, default="")
    entry_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, index=True
    )


class WalletHoldORM(TimestampMixin, Base):
    """A short-lived preauthorization for one platform-model turn.

    A hold never changes a wallet balance by itself.  It merely prevents two
    concurrent turns from spending the same credit.  Settlement writes an
    immutable ``WalletLedgerORM`` entry, then marks this record settled or
    released.  Storing the rate snapshot protects players from an operator
    changing the price while a long streamed turn is still in progress.
    """

    __tablename__ = "wallet_holds"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_wallet_hold_idempotency"),
        sa.CheckConstraint("reserved_credits > 0", name="ck_wallet_hold_positive_reserve"),
        sa.CheckConstraint(
            "cost_microunits_per_credit > 0", name="ck_wallet_hold_positive_rate"
        ),
        sa.CheckConstraint("settled_credits >= 0", name="ck_wallet_hold_nonnegative_settlement"),
        sa.CheckConstraint(
            "settled_credits <= reserved_credits", name="ck_wallet_hold_settlement_within_reserve"
        ),
        sa.CheckConstraint(
            "status IN ('held', 'settled', 'released', 'capped')", name="ck_wallet_hold_valid_status"
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    playthrough_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("playthroughs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(sa.String(120))
    status: Mapped[str] = mapped_column(sa.String(24), default="held", index=True)
    reserved_credits: Mapped[int] = mapped_column(sa.BigInteger)
    settled_credits: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    cost_microunits_per_credit: Mapped[int] = mapped_column(sa.BigInteger)
    wallet_ledger_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("wallet_ledger.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)
    hold_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class PaymentOrderORM(TimestampMixin, Base):
    """A provider-neutral, immutable price snapshot for a checkout attempt.

    Payment processor objects are external evidence, not the balance source of
    truth.  A verified payment writes one corresponding ``WalletLedgerORM``
    credit entry.  This table keeps the price, currency and channel that the
    player actually saw so later catalog changes cannot rewrite history.
    """

    __tablename__ = "payment_orders"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_payment_order_idempotency"),
        sa.UniqueConstraint("provider", "provider_reference", name="uq_payment_order_provider_ref"),
        sa.CheckConstraint("amount_minor >= 0", name="ck_payment_order_nonnegative_amount"),
        sa.CheckConstraint("credit_amount > 0", name="ck_payment_order_positive_credits"),
        sa.Index("ix_payment_orders_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    plan_code: Mapped[str] = mapped_column(sa.String(80), default="")
    provider: Mapped[str] = mapped_column(sa.String(40), default="")
    provider_reference: Mapped[str | None] = mapped_column(sa.String(160), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(32), default="created", index=True)
    currency: Mapped[str] = mapped_column(sa.String(8), default="CNY")
    amount_minor: Mapped[int] = mapped_column(sa.BigInteger)
    credit_amount: Mapped[int] = mapped_column(sa.BigInteger)
    idempotency_key: Mapped[str] = mapped_column(sa.String(120))
    checkout_url: Mapped[str | None] = mapped_column(sa.String(1_000), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    order_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class CreditCampaignORM(TimestampMixin, Base):
    """A bounded, non-cash promotional credit grant.

    Campaigns do not represent a payment method or a transferable balance.
    Each successful redemption still creates a normal immutable wallet ledger
    entry, allowing operators to reverse a mistaken grant without editing
    campaign history or a player's balance in place.
    """

    __tablename__ = "credit_campaigns"
    __table_args__ = (
        sa.CheckConstraint("credit_amount > 0", name="ck_credit_campaign_positive_credits"),
        sa.CheckConstraint("redemption_count >= 0", name="ck_credit_campaign_nonnegative_redemptions"),
        sa.CheckConstraint(
            "max_redemptions IS NULL OR max_redemptions > 0",
            name="ck_credit_campaign_positive_cap",
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_credit_campaign_valid_window"),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'ended')",
            name="ck_credit_campaign_valid_status",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    code: Mapped[str] = mapped_column(sa.String(48), unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(100))
    description: Mapped[str] = mapped_column(sa.String(500), default="")
    credit_amount: Mapped[int] = mapped_column(sa.BigInteger)
    status: Mapped[str] = mapped_column(sa.String(16), default="draft", index=True)
    starts_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)
    max_redemptions: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    redemption_count: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    created_by: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class SupportCaseORM(TimestampMixin, Base):
    """A player-owned support case with an auditable operator lifecycle.

    A case deliberately contains only the player-provided issue description and
    an optional playthrough reference.  It never snapshots story prose, model
    credentials, payment instruments, IP addresses or internal diagnostics.
    """

    __tablename__ = "support_cases"
    __table_args__ = (
        sa.CheckConstraint(
            "category IN ('account', 'billing', 'playthrough', 'technical', 'content', 'other')",
            name="ck_support_case_category",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'waiting_user', 'resolved', 'closed')",
            name="ck_support_case_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="ck_support_case_priority",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    playthrough_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("playthroughs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(sa.String(24), default="other", index=True)
    status: Mapped[str] = mapped_column(sa.String(24), default="open", index=True)
    priority: Mapped[str] = mapped_column(sa.String(16), default="normal", index=True)
    subject: Mapped[str] = mapped_column(sa.String(140))
    assigned_to: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )


class SupportCaseMessageORM(Base):
    """Append-only player/operator conversation for a support case."""

    __tablename__ = "support_case_messages"
    __table_args__ = (
        sa.CheckConstraint(
            "author_role IN ('player', 'admin')", name="ck_support_case_message_author_role"
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("support_cases.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    author_role: Mapped[str] = mapped_column(sa.String(16))
    body: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, index=True
    )


class UserNotificationORM(Base):
    """A small, player-owned in-product notification inbox entry."""

    __tablename__ = "user_notifications"
    __table_args__ = (
        sa.CheckConstraint("length(title) > 0", name="ck_user_notification_title"),
        sa.CheckConstraint("length(href) > 0", name="ck_user_notification_href"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(sa.String(64), index=True)
    title: Mapped[str] = mapped_column(sa.String(160))
    body: Mapped[str] = mapped_column(sa.String(500), default="")
    href: Mapped[str] = mapped_column(sa.String(500))
    read_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, index=True
    )


class SuperAdminApprovalORM(TimestampMixin, Base):
    """Dual-control record for the platform's break-glass administrator role.

    A request is never a role change by itself.  A different super
    administrator must approve it before the dedicated governance endpoint
    changes ``user_roles``.  Retaining terminal requests makes elevation and
    demotion reviewable even after an operator account is later scrubbed.
    """

    __tablename__ = "super_admin_approvals"
    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled', 'expired')",
            name="ck_super_admin_approval_status",
        ),
        sa.CheckConstraint("length(request_reason) > 0", name="ck_super_admin_approval_reason"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    requester_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    target_user_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    requested_enabled: Mapped[bool] = mapped_column(sa.Boolean)
    request_reason: Mapped[str] = mapped_column(sa.String(500))
    status: Mapped[str] = mapped_column(sa.String(16), default="pending", index=True)
    approver_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    decision_reason: Mapped[str] = mapped_column(sa.String(500), default="")
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)
    executed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class DataExportORM(TimestampMixin, Base):
    __tablename__ = "data_exports"
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(sa.String(24), default="queued", index=True)
    object_key: Mapped[str | None] = mapped_column(sa.String(500), nullable=True, unique=True)
    byte_size: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    error_code: Mapped[str] = mapped_column(sa.String(80), default="")
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)


class ProductEventORM(Base):
    """Consent-gated, allow-listed product event used for aggregate funnels."""

    __tablename__ = "product_events"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "event_name", "dedupe_key", name="uq_product_event_dedupe"),
    )
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    event_name: Mapped[str] = mapped_column(sa.String(80), index=True)
    dedupe_key: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    playthrough_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("playthroughs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    release_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("content_releases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_properties: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, index=True
    )


class ModerationCaseORM(TimestampMixin, Base):
    __tablename__ = "moderation_cases"
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    release_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("content_releases.id", ondelete="CASCADE"), index=True
    )
    submitter_id: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("users.id"))
    reviewer_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(sa.String(32), default="pending", index=True)
    decision_reason: Mapped[str] = mapped_column(sa.Text, default="")
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)


class ReportORM(TimestampMixin, Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    reporter_id: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("users.id"), index=True)
    release_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("content_releases.id"), index=True
    )
    category: Mapped[str] = mapped_column(sa.String(60))
    details: Mapped[str] = mapped_column(sa.Text, default="")
    status: Mapped[str] = mapped_column(sa.String(24), default="open", index=True)


class AuditLogORM(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    actor_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    action: Mapped[str] = mapped_column(sa.String(120), index=True)
    target_type: Mapped[str] = mapped_column(sa.String(60))
    target_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    request_id: Mapped[str] = mapped_column(sa.String(64), default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, index=True
    )
