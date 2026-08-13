"""asynchronous personal data exports

Revision ID: d11a63e8bf20
Revises: ca9102e4d731
Create Date: 2026-08-13 06:15:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d11a63e8bf20"
down_revision: str | None = "ca9102e4d731"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_exports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index("ix_data_exports_user_id", "data_exports", ["user_id"])
    op.create_index("ix_data_exports_status", "data_exports", ["status"])
    op.create_index("ix_data_exports_expires_at", "data_exports", ["expires_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text('ALTER TABLE "data_exports" ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text('ALTER TABLE "data_exports" FORCE ROW LEVEL SECURITY'))
        identity = "NULLIF(current_setting('app.current_user_id', true), '')"
        op.execute(
            sa.text(
                "CREATE POLICY data_exports_tenant_policy ON data_exports FOR ALL "
                f"USING (user_id = {identity}) WITH CHECK (user_id = {identity})"
            )
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("DROP POLICY IF EXISTS data_exports_tenant_policy ON data_exports"))
    op.drop_index("ix_data_exports_expires_at", table_name="data_exports")
    op.drop_index("ix_data_exports_status", table_name="data_exports")
    op.drop_index("ix_data_exports_user_id", table_name="data_exports")
    op.drop_table("data_exports")
