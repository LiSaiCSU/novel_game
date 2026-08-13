"""add non-enumerable project preview token

Revision ID: c82fa6d40b31
Revises: b71d8ae3920f
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c82fa6d40b31"
down_revision: str | None = "b71d8ae3920f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("share_token_hash", sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint("uq_projects_share_token_hash", ["share_token_hash"])


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_constraint("uq_projects_share_token_hash", type_="unique")
        batch_op.drop_column("share_token_hash")
