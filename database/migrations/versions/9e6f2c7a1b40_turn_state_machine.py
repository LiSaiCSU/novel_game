"""add recoverable turn state machine

Revision ID: 9e6f2c7a1b40
Revises: 52add84b754e
Create Date: 2026-08-09 15:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9e6f2c7a1b40"
down_revision: Union[str, None] = "52add84b754e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("turns") as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(length=40),
                nullable=False,
                server_default="COMPLETED",
            )
        )
        batch_op.add_column(
            sa.Column("canonical_payload", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.add_column(
            sa.Column("last_error", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.create_index("ix_turns_status", ["status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("turns") as batch_op:
        batch_op.drop_index("ix_turns_status")
        batch_op.drop_column("last_error")
        batch_op.drop_column("canonical_payload")
        batch_op.drop_column("status")
