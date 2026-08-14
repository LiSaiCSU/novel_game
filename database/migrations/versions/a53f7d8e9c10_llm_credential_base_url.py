"""add BYOK compatible-provider base URL

Revision ID: a53f7d8e9c10
Revises: e91c37a2b604
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a53f7d8e9c10"
down_revision: str | None = "e91c37a2b604"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("llm_credentials") as batch_op:
        batch_op.add_column(
            sa.Column("base_url", sa.String(length=500), nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("llm_credentials") as batch_op:
        batch_op.drop_column("base_url")
