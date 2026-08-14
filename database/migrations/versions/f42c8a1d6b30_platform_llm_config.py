"""add encrypted platform LLM configuration

Revision ID: f42c8a1d6b30
Revises: a53f7d8e9c10
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from database.base import JSONType

revision: str = "f42c8a1d6b30"
down_revision: str | None = "a53f7d8e9c10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_llm_config",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("provider", sa.String(length=60), nullable=False, server_default="null"),
        sa.Column("model", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("base_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("encrypted_secret", sa.Text(), nullable=True),
        sa.Column("key_hint", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("extra_body", JSONType, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("platform_llm_config")
