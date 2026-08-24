"""add bounded promotional credit campaigns

Revision ID: c56a9e3d4f11
Revises: b84a7c5e2d11
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c56a9e3d4f11"
down_revision: str | None = "b84a7c5e2d11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_campaign_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    identity = "NULLIF(current_setting('app.current_user_id', true), '')"
    is_admin = (
        "EXISTS (SELECT 1 FROM user_roles ur "
        f"WHERE ur.user_id = {identity} AND ur.role = 'admin')"
    )
    active_window = "status = 'active' AND starts_at <= now() AND ends_at > now()"
    op.execute(sa.text('ALTER TABLE "credit_campaigns" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "credit_campaigns" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            "CREATE POLICY credit_campaigns_player_active_read_policy ON credit_campaigns "
            f"FOR SELECT USING ({active_window})"
        )
    )
    # Player redemption increments only a currently claimable campaign. The
    # application transaction locks the row and enforces the cap before this
    # update; RLS ensures a player transaction cannot touch paused/draft rows.
    op.execute(
        sa.text(
            "CREATE POLICY credit_campaigns_player_redeem_update_policy ON credit_campaigns "
            f"FOR UPDATE USING ({active_window}) WITH CHECK ({active_window})"
        )
    )
    for action, clause in (
        ("SELECT", f"USING ({is_admin})"),
        ("INSERT", f"WITH CHECK ({is_admin})"),
        ("UPDATE", f"USING ({is_admin}) WITH CHECK ({is_admin})"),
    ):
        op.execute(
            sa.text(
                f"CREATE POLICY credit_campaigns_admin_{action.lower()}_policy "
                f"ON credit_campaigns FOR {action} {clause}"
            )
        )


def upgrade() -> None:
    op.create_table(
        "credit_campaigns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("credit_amount", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_redemptions", sa.BigInteger(), nullable=True),
        sa.Column("redemption_count", sa.BigInteger(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("credit_amount > 0", name="ck_credit_campaign_positive_credits"),
        sa.CheckConstraint("redemption_count >= 0", name="ck_credit_campaign_nonnegative_redemptions"),
        sa.CheckConstraint(
            "max_redemptions IS NULL OR max_redemptions > 0",
            name="ck_credit_campaign_positive_cap",
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_credit_campaign_valid_window"),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'ended')",
            name="ck_credit_campaign_valid_status",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("code", "status", "starts_at", "ends_at"):
        op.create_index(
            f"ix_credit_campaigns_{column}",
            "credit_campaigns",
            [column],
            unique=column == "code",
        )
    _enable_campaign_rls()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for policy in (
            "credit_campaigns_admin_update_policy",
            "credit_campaigns_admin_insert_policy",
            "credit_campaigns_admin_select_policy",
            "credit_campaigns_player_redeem_update_policy",
            "credit_campaigns_player_active_read_policy",
        ):
            op.execute(sa.text(f"DROP POLICY IF EXISTS {policy} ON credit_campaigns"))
    for column in ("ends_at", "starts_at", "status", "code"):
        op.drop_index(f"ix_credit_campaigns_{column}", table_name="credit_campaigns")
    op.drop_table("credit_campaigns")
