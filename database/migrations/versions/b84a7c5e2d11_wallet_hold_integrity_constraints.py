"""enforce wallet hold state and settlement boundaries

Revision ID: b84a7c5e2d11
Revises: 9f2c1d6e4a80
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b84a7c5e2d11"
down_revision: str | None = "9f2c1d6e4a80"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode keeps SQLite development databases migratable while emitting
    # ordinary ALTER TABLE constraints on PostgreSQL production databases.
    with op.batch_alter_table("wallet_holds") as batch:
        batch.create_check_constraint(
            "ck_wallet_hold_settlement_within_reserve", "settled_credits <= reserved_credits"
        )
        batch.create_check_constraint(
            "ck_wallet_hold_valid_status", "status IN ('held', 'settled', 'released', 'capped')"
        )


def downgrade() -> None:
    with op.batch_alter_table("wallet_holds") as batch:
        batch.drop_constraint("ck_wallet_hold_valid_status", type_="check")
        batch.drop_constraint("ck_wallet_hold_settlement_within_reserve", type_="check")
