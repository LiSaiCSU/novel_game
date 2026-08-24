"""add player notification inbox

Revision ID: a4f9c2d8e603
Revises: d2e8b6c3f407
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4f9c2d8e603"
down_revision: str | None = "d2e8b6c3f407"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_notification_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    identity = "NULLIF(current_setting('app.current_user_id', true), '')"
    is_admin = (
        "EXISTS (SELECT 1 FROM user_roles ur "
        f"WHERE ur.user_id = {identity} AND ur.role = 'admin')"
    )
    owner = f"user_id = {identity}"
    op.execute(sa.text('ALTER TABLE "user_notifications" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "user_notifications" FORCE ROW LEVEL SECURITY'))
    for action, clause in (
        ("SELECT", f"USING ({owner})"),
        ("INSERT", f"WITH CHECK ({owner})"),
        ("UPDATE", f"USING ({owner}) WITH CHECK ({owner})"),
        # Account scrubbing runs with the former user's tenant identity. The
        # browser has no delete endpoint for inbox history.
        ("DELETE", f"USING ({owner})"),
    ):
        op.execute(
            sa.text(
                f"CREATE POLICY user_notifications_owner_{action.lower()}_policy "
                f"ON user_notifications FOR {action} {clause}"
            )
        )
    for action, clause in (
        ("SELECT", f"USING ({is_admin})"),
        ("INSERT", f"WITH CHECK ({is_admin})"),
        ("UPDATE", f"USING ({is_admin}) WITH CHECK ({is_admin})"),
    ):
        op.execute(
            sa.text(
                f"CREATE POLICY user_notifications_admin_{action.lower()}_policy "
                f"ON user_notifications FOR {action} {clause}"
            )
        )


def upgrade() -> None:
    op.create_table(
        "user_notifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("body", sa.String(length=500), nullable=False),
        sa.Column("href", sa.String(length=500), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(title) > 0", name="ck_user_notification_title"),
        sa.CheckConstraint("length(href) > 0", name="ck_user_notification_href"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("user_id", "kind", "read_at", "created_at"):
        op.create_index(f"ix_user_notifications_{column}", "user_notifications", [column])
    _enable_notification_rls()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for policy in (
            "user_notifications_admin_update_policy",
            "user_notifications_admin_insert_policy",
            "user_notifications_admin_select_policy",
            "user_notifications_owner_delete_policy",
            "user_notifications_owner_update_policy",
            "user_notifications_owner_insert_policy",
            "user_notifications_owner_select_policy",
        ):
            op.execute(sa.text(f"DROP POLICY IF EXISTS {policy} ON user_notifications"))
    for column in ("created_at", "read_at", "kind", "user_id"):
        op.drop_index(f"ix_user_notifications_{column}", table_name="user_notifications")
    op.drop_table("user_notifications")
