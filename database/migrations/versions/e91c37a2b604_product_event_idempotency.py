"""product event idempotency

Revision ID: e91c37a2b604
Revises: a42f06d3c9e1
Create Date: 2026-08-13 14:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e91c37a2b604"
down_revision: str | None = "a42f06d3c9e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("product_events") as batch_op:
        batch_op.add_column(sa.Column("dedupe_key", sa.String(length=120), nullable=True))
        batch_op.create_unique_constraint(
            "uq_product_event_dedupe", ["user_id", "event_name", "dedupe_key"]
        )


def downgrade() -> None:
    with op.batch_alter_table("product_events") as batch_op:
        batch_op.drop_constraint("uq_product_event_dedupe", type_="unique")
        batch_op.drop_column("dedupe_key")
