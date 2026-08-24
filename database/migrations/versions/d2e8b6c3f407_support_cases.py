"""add player support cases and append-only replies

Revision ID: d2e8b6c3f407
Revises: c56a9e3d4f11
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2e8b6c3f407"
down_revision: str | None = "c56a9e3d4f11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_support_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    identity = "NULLIF(current_setting('app.current_user_id', true), '')"
    is_admin = (
        "EXISTS (SELECT 1 FROM user_roles ur "
        f"WHERE ur.user_id = {identity} AND ur.role = 'admin')"
    )
    owner_case = f"user_id = {identity}"
    owner_message = (
        "EXISTS (SELECT 1 FROM support_cases sc "
        f"WHERE sc.id = case_id AND sc.user_id = {identity})"
    )
    active_owner_case = (
        "EXISTS (SELECT 1 FROM support_cases sc "
        f"WHERE sc.id = case_id AND sc.user_id = {identity} "
        "AND sc.status IN ('open', 'in_progress', 'waiting_user'))"
    )
    for table in ("support_cases", "support_case_messages"):
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))

    op.execute(
        sa.text(
            "CREATE POLICY support_cases_owner_select_policy ON support_cases FOR SELECT "
            f"USING ({owner_case})"
        )
    )
    op.execute(
        sa.text(
            "CREATE POLICY support_cases_owner_insert_policy ON support_cases FOR INSERT "
            f"WITH CHECK ({owner_case})"
        )
    )
    # Account-erasure worker runs with the former owner's tenant context, so
    # it can erase the player's correspondence without acquiring a broad DB
    # bypass role. No player-facing endpoint deletes cases.
    op.execute(
        sa.text(
            "CREATE POLICY support_cases_owner_delete_policy ON support_cases FOR DELETE "
            f"USING ({owner_case})"
        )
    )
    for action, clause in (
        ("SELECT", f"USING ({is_admin})"),
        ("INSERT", f"WITH CHECK ({is_admin})"),
        ("UPDATE", f"USING ({is_admin}) WITH CHECK ({is_admin})"),
    ):
        op.execute(
            sa.text(
                f"CREATE POLICY support_cases_admin_{action.lower()}_policy "
                f"ON support_cases FOR {action} {clause}"
            )
        )

    op.execute(
        sa.text(
            "CREATE POLICY support_case_messages_owner_select_policy ON support_case_messages "
            f"FOR SELECT USING ({owner_message})"
        )
    )
    op.execute(
        sa.text(
            "CREATE POLICY support_case_messages_owner_insert_policy ON support_case_messages "
            "FOR INSERT WITH CHECK ("
            f"author_id = {identity} AND author_role = 'player' AND {active_owner_case}"
            ")"
        )
    )
    for action, clause in (
        ("SELECT", f"USING ({is_admin})"),
        ("INSERT", f"WITH CHECK ({is_admin})"),
    ):
        op.execute(
            sa.text(
                f"CREATE POLICY support_case_messages_admin_{action.lower()}_policy "
                f"ON support_case_messages FOR {action} {clause}"
            )
        )


def upgrade() -> None:
    op.create_table(
        "support_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("playthrough_id", sa.String(length=36), nullable=True),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=140), nullable=False),
        sa.Column("assigned_to", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "category IN ('account', 'billing', 'playthrough', 'technical', 'content', 'other')",
            name="ck_support_case_category",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'waiting_user', 'resolved', 'closed')",
            name="ck_support_case_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="ck_support_case_priority",
        ),
        sa.ForeignKeyConstraint(["assigned_to"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["playthrough_id"], ["playthroughs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("user_id", "playthrough_id", "category", "status", "priority", "assigned_to"):
        op.create_index(f"ix_support_cases_{column}", "support_cases", [column])
    op.create_table(
        "support_case_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("author_id", sa.String(length=36), nullable=True),
        sa.Column("author_role", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "author_role IN ('player', 'admin')", name="ck_support_case_message_author_role"
        ),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["case_id"], ["support_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("case_id", "author_id", "created_at"):
        op.create_index(
            f"ix_support_case_messages_{column}", "support_case_messages", [column]
        )
    _enable_support_rls()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for policy, table in (
            ("support_case_messages_admin_insert_policy", "support_case_messages"),
            ("support_case_messages_admin_select_policy", "support_case_messages"),
            ("support_case_messages_owner_insert_policy", "support_case_messages"),
            ("support_case_messages_owner_select_policy", "support_case_messages"),
            ("support_cases_admin_update_policy", "support_cases"),
            ("support_cases_admin_insert_policy", "support_cases"),
            ("support_cases_admin_select_policy", "support_cases"),
            ("support_cases_owner_insert_policy", "support_cases"),
            ("support_cases_owner_delete_policy", "support_cases"),
            ("support_cases_owner_select_policy", "support_cases"),
        ):
            op.execute(sa.text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
    for column in ("created_at", "author_id", "case_id"):
        op.drop_index(f"ix_support_case_messages_{column}", table_name="support_case_messages")
    op.drop_table("support_case_messages")
    for column in ("assigned_to", "priority", "status", "category", "playthrough_id", "user_id"):
        op.drop_index(f"ix_support_cases_{column}", table_name="support_cases")
    op.drop_table("support_cases")
