"""turn billing preauthorization holds

Revision ID: 9f2c1d6e4a80
Revises: f1a8d4b7c902
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9f2c1d6e4a80"
down_revision: str | None = "f1a8d4b7c902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    identity = "NULLIF(current_setting('app.current_user_id', true), '')"
    is_admin = (
        "EXISTS (SELECT 1 FROM user_roles ur "
        f"WHERE ur.user_id = {identity} AND ur.role = 'admin')"
    )
    op.execute(sa.text('ALTER TABLE "wallet_holds" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "wallet_holds" FORCE ROW LEVEL SECURITY'))
    for action, clause in (
        ("SELECT", f"USING (user_id = {identity})"),
        ("INSERT", f"WITH CHECK (user_id = {identity})"),
        ("UPDATE", f"USING (user_id = {identity}) WITH CHECK (user_id = {identity})"),
    ):
        op.execute(
            sa.text(f"CREATE POLICY wallet_holds_owner_{action.lower()}_policy "
                    f"ON wallet_holds FOR {action} {clause}")
        )
    op.execute(
        sa.text(
            "CREATE POLICY wallet_holds_admin_read_policy ON wallet_holds FOR SELECT "
            f"USING ({is_admin})"
        )
    )
    # A player-scoped application transaction settles platform-model usage.
    # There is no DELETE policy: holds remain as an audit trail until retention
    # housekeeping removes only long-expired rows under a dedicated DB role.
    op.execute(
        sa.text(
            "CREATE POLICY wallet_ledger_owner_insert_policy ON wallet_ledger FOR INSERT "
            f"WITH CHECK (user_id = {identity})"
        )
    )


def upgrade() -> None:
    op.create_table(
        "wallet_holds",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("playthrough_id", sa.String(length=36), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reserved_credits", sa.BigInteger(), nullable=False),
        sa.Column("settled_credits", sa.BigInteger(), nullable=False),
        sa.Column("cost_microunits_per_credit", sa.BigInteger(), nullable=False),
        sa.Column("wallet_ledger_id", sa.String(length=36), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hold_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("cost_microunits_per_credit > 0", name="ck_wallet_hold_positive_rate"),
        sa.CheckConstraint("reserved_credits > 0", name="ck_wallet_hold_positive_reserve"),
        sa.CheckConstraint("settled_credits >= 0", name="ck_wallet_hold_nonnegative_settlement"),
        sa.ForeignKeyConstraint(["playthrough_id"], ["playthroughs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["wallet_ledger_id"], ["wallet_ledger.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_wallet_hold_idempotency"),
        sa.UniqueConstraint("wallet_ledger_id"),
    )
    for column in ("user_id", "playthrough_id", "status", "expires_at"):
        op.create_index(f"ix_wallet_holds_{column}", "wallet_holds", [column])
    _enable_rls()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for policy in (
            "wallet_ledger_owner_insert_policy",
            "wallet_holds_admin_read_policy",
            "wallet_holds_owner_update_policy",
            "wallet_holds_owner_insert_policy",
            "wallet_holds_owner_select_policy",
        ):
            table = "wallet_ledger" if policy.startswith("wallet_ledger") else "wallet_holds"
            op.execute(sa.text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
    for column in ("expires_at", "status", "playthrough_id", "user_id"):
        op.drop_index(f"ix_wallet_holds_{column}", table_name="wallet_holds")
    op.drop_table("wallet_holds")
