"""persist canonical playthrough endings

Revision ID: f18b7d2ac604
Revises: e57a4c19d283
Create Date: 2026-08-13 04:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f18b7d2ac604"
down_revision: str | None = "e57a4c19d283"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("playthroughs") as batch_op:
        batch_op.add_column(sa.Column("ending_key", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("ending_title", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("playthroughs") as batch_op:
        batch_op.drop_column("completed_at")
        batch_op.drop_column("ending_title")
        batch_op.drop_column("ending_key")
