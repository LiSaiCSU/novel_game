"""make canonical event memory projection idempotent

Revision ID: d8f1c64a2e90
Revises: c3a5e82f4d71
Create Date: 2026-08-09 21:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d8f1c64a2e90"
down_revision: str | None = "c3a5e82f4d71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Older builds could write the same event memory more than once during a
    # retry.  Keep the oldest projection before installing the final guard.
    op.execute(
        """
        DELETE FROM memories
        WHERE related_event_id IS NOT NULL
          AND id NOT IN (
              SELECT MIN(id)
              FROM memories
              WHERE related_event_id IS NOT NULL
              GROUP BY owner_character_id, related_event_id
          )
        """
    )
    with op.batch_alter_table("memories") as batch_op:
        batch_op.create_unique_constraint(
            "uq_memory_owner_event",
            ["owner_character_id", "related_event_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("memories") as batch_op:
        batch_op.drop_constraint("uq_memory_owner_event", type_="unique")
