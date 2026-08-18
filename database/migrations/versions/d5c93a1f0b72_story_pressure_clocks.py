"""visible pressure clocks

A world that knows a blast is nine days out, and a faction is three steps from
identifying the player, has to be able to say so. Clocks are that pressure in
a form the interface can draw and the narrator can read.

Revision ID: d5c93a1f0b72
Revises: c4e18b7f2a05
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from database.base import JSONType

revision: str = "d5c93a1f0b72"
down_revision: str | None = "c4e18b7f2a05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_clocks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("world_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="danger"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("segments", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("filled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("minutes_per_segment", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at_minute", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("thread_key", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("consequence", sa.Text(), nullable=False, server_default=""),
        sa.Column("clock_metadata", JSONType, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("world_id", "key", name="uq_clock_world_key"),
    )
    with op.batch_alter_table("story_clocks", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_story_clocks_world_id"), ["world_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_story_clocks_status"), ["status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("story_clocks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_story_clocks_status"))
        batch_op.drop_index(batch_op.f("ix_story_clocks_world_id"))
    op.drop_table("story_clocks")
