"""save slots: named restore points holding a whole world

Revision ID: e4b9a07c3d15
Revises: d8f1c64a2e90
Create Date: 2026-08-10 10:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from database.models.orm import JSONType

revision: str = "e4b9a07c3d15"
down_revision: str | None = "d8f1c64a2e90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "save_slots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("world_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(80), nullable=False, server_default=""),
        sa.Column("player_name", sa.String(80), nullable=False, server_default=""),
        sa.Column("turn_number", sa.Integer, nullable=False, server_default="0"),
        sa.Column("world_minute", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("time_label", sa.String(120), nullable=False, server_default=""),
        sa.Column("location_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("excerpt", sa.Text, nullable=False, server_default=""),
        sa.Column("payload", JSONType, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_save_slots_session", "save_slots", ["session_id"])
    op.create_index("idx_save_slots_world", "save_slots", ["world_id"])


def downgrade() -> None:
    op.drop_index("idx_save_slots_world", table_name="save_slots")
    op.drop_index("idx_save_slots_session", table_name="save_slots")
    op.drop_table("save_slots")
