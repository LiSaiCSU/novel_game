"""add dual approval for super administrator changes

Revision ID: e7c2b9f4a108
Revises: a4f9c2d8e603
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7c2b9f4a108"
down_revision: str | None = "a4f9c2d8e603"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_approval_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    identity = "NULLIF(current_setting('app.current_user_id', true), '')"
    is_super_admin = (
        "EXISTS (SELECT 1 FROM user_roles ur "
        f"WHERE ur.user_id = {identity} AND ur.role = 'super_admin')"
    )
    op.execute(sa.text('ALTER TABLE "super_admin_approvals" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "super_admin_approvals" FORCE ROW LEVEL SECURITY'))
    for action, clause in (
        ("SELECT", f"USING ({is_super_admin})"),
        ("INSERT", f"WITH CHECK ({is_super_admin})"),
        ("UPDATE", f"USING ({is_super_admin}) WITH CHECK ({is_super_admin})"),
    ):
        op.execute(
            sa.text(
                f"CREATE POLICY super_admin_approvals_{action.lower()}_policy "
                f"ON super_admin_approvals FOR {action} {clause}"
            )
        )


def upgrade() -> None:
    op.create_table(
        "super_admin_approvals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("requester_id", sa.String(length=36), nullable=False),
        sa.Column("target_user_id", sa.String(length=36), nullable=False),
        sa.Column("requested_enabled", sa.Boolean(), nullable=False),
        sa.Column("request_reason", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("approver_id", sa.String(length=36), nullable=True),
        sa.Column("decision_reason", sa.String(length=500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled', 'expired')",
            name="ck_super_admin_approval_status",
        ),
        sa.CheckConstraint("length(request_reason) > 0", name="ck_super_admin_approval_reason"),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("requester_id", "target_user_id", "status", "approver_id", "expires_at"):
        op.create_index(f"ix_super_admin_approvals_{column}", "super_admin_approvals", [column])
    _enable_approval_rls()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for action in ("update", "insert", "select"):
            op.execute(
                sa.text(
                    f"DROP POLICY IF EXISTS super_admin_approvals_{action}_policy "
                    "ON super_admin_approvals"
                )
            )
    for column in ("expires_at", "approver_id", "status", "target_user_id", "requester_id"):
        op.drop_index(f"ix_super_admin_approvals_{column}", table_name="super_admin_approvals")
    op.drop_table("super_admin_approvals")
