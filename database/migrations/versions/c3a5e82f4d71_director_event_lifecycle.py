"""add Director event lifecycle

Revision ID: c3a5e82f4d71
Revises: b7d4a91e6c20
Create Date: 2026-08-09 19:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3a5e82f4d71"
down_revision: Union[str, None] = "b7d4a91e6c20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "director_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("world_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("created_turn_id", sa.String(length=36), nullable=False),
        sa.Column("created_turn_number", sa.Integer(), nullable=False),
        sa.Column("dedup_key", sa.String(length=64), nullable=False),
        sa.Column("decision_type", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source_plot_thread_id", sa.String(length=36), nullable=True),
        sa.Column("source_plot_thread_key", sa.String(length=120), nullable=True),
        sa.Column("source_plot_thread_stage", sa.Integer(), nullable=True),
        sa.Column("participant_keys", sa.JSON(), nullable=False),
        sa.Column("participant_ids", sa.JSON(), nullable=False),
        sa.Column("location_id", sa.String(length=36), nullable=True),
        sa.Column("proposal", sa.Text(), nullable=False),
        sa.Column("causal_basis", sa.JSON(), nullable=False),
        sa.Column("narrative_purpose", sa.JSON(), nullable=False),
        sa.Column("urgency", sa.String(length=40), nullable=False),
        sa.Column("tension_delta", sa.Float(), nullable=False),
        sa.Column("proposed_at_minute", sa.BigInteger(), nullable=False),
        sa.Column("scheduled_for_minute", sa.BigInteger(), nullable=False),
        sa.Column("activated_at_minute", sa.BigInteger(), nullable=True),
        sa.Column("resolved_at_minute", sa.BigInteger(), nullable=True),
        sa.Column("cancelled_at_minute", sa.BigInteger(), nullable=True),
        sa.Column("canonical_event_id", sa.String(length=36), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("world_id", "dedup_key", name="uq_director_event_world_dedup"),
    )
    op.create_index("ix_director_events_world_id", "director_events", ["world_id"])
    op.create_index("ix_director_events_session_id", "director_events", ["session_id"])
    op.create_index("ix_director_events_created_turn_id", "director_events", ["created_turn_id"])
    op.create_index("ix_director_events_status", "director_events", ["status"])
    op.create_index(
        "ix_director_events_scheduled_for_minute",
        "director_events",
        ["scheduled_for_minute"],
    )
    op.create_index(
        "idx_director_events_due",
        "director_events",
        ["world_id", "status", "scheduled_for_minute"],
    )
    op.create_index(
        "idx_director_events_session_turn",
        "director_events",
        ["session_id", "created_turn_number"],
    )


def downgrade() -> None:
    op.drop_table("director_events")
