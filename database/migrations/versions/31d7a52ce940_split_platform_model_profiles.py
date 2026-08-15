"""split platform narrative and reasoning model profiles

Revision ID: 31d7a52ce940
Revises: f42c8a1d6b30
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from database.base import JSONType

revision: str = "31d7a52ce940"
down_revision: str | None = "f42c8a1d6b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "platform_llm_config",
        sa.Column("reasoning_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "platform_llm_config",
        sa.Column("reasoning_model", sa.String(length=160), nullable=False, server_default=""),
    )
    op.add_column(
        "platform_llm_config",
        sa.Column(
            "reasoning_extra_body", JSONType, nullable=False, server_default=sa.text("'{}'")
        ),
    )


def downgrade() -> None:
    op.drop_column("platform_llm_config", "reasoning_extra_body")
    op.drop_column("platform_llm_config", "reasoning_model")
    op.drop_column("platform_llm_config", "reasoning_enabled")
