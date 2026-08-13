"""record relationship boundary awareness

Revision ID: 9a02f15d62c8
Revises: 63d6d2f41ef9
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9a02f15d62c8"
down_revision: str | None = "63d6d2f41ef9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("relationships") as batch_op:
        batch_op.add_column(
            sa.Column("boundaries", sa.Integer(), nullable=False, server_default="50")
        )


def downgrade() -> None:
    with op.batch_alter_table("relationships") as batch_op:
        batch_op.drop_column("boundaries")
