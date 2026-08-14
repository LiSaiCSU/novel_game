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


class PlatformLlmConfigORM(TimestampMixin, Base):
    """Encrypted singleton configuration for the platform-funded model."""

    __tablename__ = "platform_llm_config"
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    provider: Mapped[str] = mapped_column(sa.String(60), default="null")
    model: Mapped[str] = mapped_column(sa.String(160), default="")
    base_url: Mapped[str] = mapped_column(sa.String(500), default="")
    encrypted_secret: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    key_hint: Mapped[str] = mapped_column(sa.String(16), default="")
    extra_body: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
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
