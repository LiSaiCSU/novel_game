"""add BYOK model selection

Revision ID: 63d6d2f41ef9
Revises: 2854c8807876
Create Date: 2026-08-13
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "63d6d2f41ef9"
down_revision: str | None = "2854c8807876"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("llm_credentials") as batch_op:
        batch_op.add_column(
            sa.Column("default_model", sa.String(length=160), nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("llm_credentials") as batch_op:
        batch_op.drop_column("default_model")
