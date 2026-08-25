"""replace the single platform model row with an ordered endpoint chain

Revision ID: a1d5f8c2e740
Revises: e7c2b9f4a108
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1d5f8c2e740"
down_revision: str | None = "e7c2b9f4a108"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "platform_llm_endpoints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("provider", sa.String(60), nullable=False, server_default="compatible"),
        sa.Column("base_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("encrypted_secret", sa.Text(), nullable=True),
        sa.Column("key_hint", sa.String(16), nullable=False, server_default=""),
        sa.Column("narrative_model", sa.String(160), nullable=False, server_default=""),
        sa.Column("reasoning_model", sa.String(160), nullable=False, server_default=""),
        sa.Column("narrative_extra_body", _JSON, nullable=False, server_default="{}"),
        sa.Column("reasoning_extra_body", _JSON, nullable=False, server_default="{}"),
        sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(200), nullable=False, server_default=""),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_platform_llm_endpoints_priority", "platform_llm_endpoints", ["priority"]
    )

    # Carry the existing single configuration across as the first endpoint so a
    # running deployment keeps answering turns without an operator re-entering
    # a credential the console can never show them again.
    connection = op.get_bind()
    existing = connection.execute(
        sa.text(
            "SELECT id, enabled, provider, model, base_url, encrypted_secret, key_hint, "
            "extra_body, reasoning_enabled, reasoning_model, reasoning_extra_body, updated_by "
            "FROM platform_llm_config"
        )
    ).mappings().first()
    if existing is not None:
        reasoning_model = (
            existing["reasoning_model"]
            if existing["reasoning_enabled"] and existing["reasoning_model"]
            else existing["model"]
        )
        reasoning_extra = (
            existing["reasoning_extra_body"]
            if existing["reasoning_enabled"]
            else existing["extra_body"]
        )
        connection.execute(
            sa.text(
                "INSERT INTO platform_llm_endpoints "
                "(id, name, enabled, priority, provider, base_url, encrypted_secret, key_hint, "
                " narrative_model, reasoning_model, narrative_extra_body, reasoning_extra_body, "
                " last_error, consecutive_failures, updated_by, created_at, updated_at) "
                "VALUES (:id, :name, :enabled, 0, :provider, :base_url, :secret, :hint, "
                " :narrative_model, :reasoning_model, :narrative_extra, :reasoning_extra, "
                " '', 0, :updated_by, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ).bindparams(
                sa.bindparam("narrative_extra", type_=_JSON),
                sa.bindparam("reasoning_extra", type_=_JSON),
            ),
            {
                "id": existing["id"],
                "name": "主用端点",
                "enabled": existing["enabled"],
                "provider": existing["provider"],
                "base_url": existing["base_url"] or "",
                "secret": existing["encrypted_secret"],
                "hint": existing["key_hint"] or "",
                "narrative_model": existing["model"] or "",
                "reasoning_model": reasoning_model or "",
                "narrative_extra": existing["extra_body"] or {},
                "reasoning_extra": reasoning_extra or {},
                "updated_by": existing["updated_by"],
            },
        )


def downgrade() -> None:
    op.drop_index("idx_platform_llm_endpoints_priority", table_name="platform_llm_endpoints")
    op.drop_table("platform_llm_endpoints")
