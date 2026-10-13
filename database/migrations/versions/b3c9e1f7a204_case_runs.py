"""add deduction case runs

Revision ID: b3c9e1f7a204
Revises: a1d5f8c2e740
Create Date: 2026-10-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b3c9e1f7a204"
down_revision: str | None = "a1d5f8c2e740"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _enable_case_run_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    identity = "NULLIF(current_setting('app.current_user_id', true), '')"
    owner = f"user_id = {identity}"
    op.execute(sa.text('ALTER TABLE "case_runs" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "case_runs" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            f"CREATE POLICY case_runs_owner_policy ON case_runs "
            f"USING ({owner}) WITH CHECK ({owner})"
        )
    )


def upgrade() -> None:
    op.create_table(
        "case_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("case_key", sa.String(length=80), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("ending", sa.String(length=80), nullable=True),
        sa.Column("state", _JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("user_id", "case_key", "status"):
        op.create_index(f"ix_case_runs_{column}", "case_runs", [column])
    _enable_case_run_rls()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("DROP POLICY IF EXISTS case_runs_owner_policy ON case_runs"))
    for column in ("status", "case_key", "user_id"):
        op.drop_index(f"ix_case_runs_{column}", table_name="case_runs")
    op.drop_table("case_runs")
