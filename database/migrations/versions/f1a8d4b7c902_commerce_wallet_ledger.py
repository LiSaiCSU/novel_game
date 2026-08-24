"""add append-only wallet and payment order foundations

Revision ID: f1a8d4b7c902
Revises: e8b247d1c390
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a8d4b7c902"
down_revision: str | None = "e8b247d1c390"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_wallet_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    identity = "NULLIF(current_setting('app.current_user_id', true), '')"
    is_admin = (
        "EXISTS (SELECT 1 FROM user_roles ur "
        f"WHERE ur.user_id = {identity} AND ur.role = 'admin')"
    )
    for table in ("wallet_ledger", "payment_orders"):
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))

    # Players see their own immutable entries.  Only a server-side transaction
    # in an authenticated administrative path can create an adjustment.
    op.execute(
        sa.text(
            "CREATE POLICY wallet_ledger_owner_read_policy ON wallet_ledger FOR SELECT "
            f"USING (user_id = {identity})"
        )
    )
    op.execute(
        sa.text(
            "CREATE POLICY wallet_ledger_admin_read_policy ON wallet_ledger FOR SELECT "
            f"USING ({is_admin})"
        )
    )
    op.execute(
        sa.text(
            "CREATE POLICY wallet_ledger_admin_insert_policy ON wallet_ledger FOR INSERT "
            f"WITH CHECK ({is_admin})"
        )
    )

    # Checkout attempts are visible to their owner.  No browser-facing role
    # can alter settlement state; webhook workers use a narrowly scoped DB
    # role in the production deployment.
    op.execute(
        sa.text(
            "CREATE POLICY payment_orders_owner_read_policy ON payment_orders FOR SELECT "
            f"USING (user_id = {identity})"
        )
    )
    op.execute(
        sa.text(
            "CREATE POLICY payment_orders_owner_insert_policy ON payment_orders FOR INSERT "
            f"WITH CHECK (user_id = {identity})"
        )
    )
    op.execute(
        sa.text(
            "CREATE POLICY payment_orders_admin_read_policy ON payment_orders FOR SELECT "
            f"USING ({is_admin})"
        )
    )


def upgrade() -> None:
    op.create_table(
        "wallet_ledger",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("credit_delta", sa.BigInteger(), nullable=False),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("entry_metadata", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("credit_delta <> 0", name="ck_wallet_ledger_nonzero_delta"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_wallet_ledger_idempotency"),
    )
    for column in ("user_id", "entry_type", "source_id", "actor_id", "created_at"):
        op.create_index(f"ix_wallet_ledger_{column}", "wallet_ledger", [column])

    op.create_table(
        "payment_orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("plan_code", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_reference", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("credit_amount", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("checkout_url", sa.String(length=1000), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("order_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_minor >= 0", name="ck_payment_order_nonnegative_amount"),
        sa.CheckConstraint("credit_amount > 0", name="ck_payment_order_positive_credits"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_reference", name="uq_payment_order_provider_ref"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_payment_order_idempotency"),
    )
    for column in ("user_id", "status", "created_at"):
        op.create_index(f"ix_payment_orders_{column}", "payment_orders", [column])
    _enable_wallet_rls()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for policy, table in (
            ("payment_orders_admin_read_policy", "payment_orders"),
            ("payment_orders_owner_insert_policy", "payment_orders"),
            ("payment_orders_owner_read_policy", "payment_orders"),
            ("wallet_ledger_admin_insert_policy", "wallet_ledger"),
            ("wallet_ledger_admin_read_policy", "wallet_ledger"),
            ("wallet_ledger_owner_read_policy", "wallet_ledger"),
        ):
            op.execute(sa.text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
    for column in ("created_at", "status", "user_id"):
        op.drop_index(f"ix_payment_orders_{column}", table_name="payment_orders")
    op.drop_table("payment_orders")
    for column in ("created_at", "actor_id", "source_id", "entry_type", "user_id"):
        op.drop_index(f"ix_wallet_ledger_{column}", table_name="wallet_ledger")
    op.drop_table("wallet_ledger")
