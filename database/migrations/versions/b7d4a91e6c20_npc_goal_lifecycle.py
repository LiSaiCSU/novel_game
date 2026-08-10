"""add persistent important NPC goal lifecycle

Revision ID: b7d4a91e6c20
Revises: 9e6f2c7a1b40
Create Date: 2026-08-09 17:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d4a91e6c20"
down_revision: Union[str, None] = "9e6f2c7a1b40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("characters") as batch_op:
        batch_op.add_column(
            sa.Column("goal_lifecycle", sa.JSON(), nullable=False, server_default="{}")
        )


def downgrade() -> None:
    with op.batch_alter_table("characters") as batch_op:
        batch_op.drop_column("goal_lifecycle")
