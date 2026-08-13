"""add stable creator asset keys

Revision ID: b71d8ae3920f
Revises: 9a02f15d62c8
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b71d8ae3920f"
down_revision: str | None = "9a02f15d62c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("assets") as batch_op:
        batch_op.add_column(sa.Column("logical_key", sa.String(length=80), nullable=True))
    op.execute("UPDATE assets SET logical_key = 'asset_' || replace(id, '-', '') WHERE logical_key IS NULL")
    with op.batch_alter_table("assets") as batch_op:
        batch_op.alter_column("logical_key", existing_type=sa.String(length=80), nullable=False)
        batch_op.create_unique_constraint("uq_project_asset_key", ["project_id", "logical_key"])


def downgrade() -> None:
    with op.batch_alter_table("assets") as batch_op:
        batch_op.drop_constraint("uq_project_asset_key", type_="unique")
        batch_op.drop_column("logical_key")
