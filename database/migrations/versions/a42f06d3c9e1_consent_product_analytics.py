"""consent-gated product analytics

Revision ID: a42f06d3c9e1
Revises: d11a63e8bf20
Create Date: 2026-08-13 11:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a42f06d3c9e1"
down_revision: str | None = "d11a63e8bf20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("analytics_consent", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("analytics_consent_updated_at", sa.DateTime(timezone=True), nullable=True)
        )
    op.create_table(
        "product_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("event_name", sa.String(length=80), nullable=False),
        sa.Column("playthrough_id", sa.String(length=36), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("release_id", sa.String(length=36), nullable=True),
        sa.Column(
            "event_properties",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["playthrough_id"], ["playthroughs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["release_id"], ["content_releases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "user_id", "event_name", "playthrough_id", "project_id", "release_id", "occurred_at"
    ):
        op.create_index(f"ix_product_events_{column}", "product_events", [column])
    if op.get_bind().dialect.name == "postgresql":
        identity = "NULLIF(current_setting('app.current_user_id', true), '')"
        op.execute(sa.text('ALTER TABLE "product_events" ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text('ALTER TABLE "product_events" FORCE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                "CREATE POLICY product_events_tenant_policy ON product_events FOR ALL "
                f"USING (user_id = {identity}) WITH CHECK (user_id = {identity})"
            )
        )
        op.execute(
            sa.text(
                "CREATE POLICY product_events_admin_read_policy ON product_events FOR SELECT "
                "USING (EXISTS (SELECT 1 FROM user_roles ur "
                f"WHERE ur.user_id = {identity} AND ur.role = 'admin'))"
            )
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("DROP POLICY IF EXISTS product_events_admin_read_policy ON product_events"))
        op.execute(sa.text("DROP POLICY IF EXISTS product_events_tenant_policy ON product_events"))
    for column in (
        "occurred_at", "release_id", "project_id", "playthrough_id", "event_name", "user_id"
    ):
        op.drop_index(f"ix_product_events_{column}", table_name="product_events")
    op.drop_table("product_events")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("analytics_consent_updated_at")
        batch_op.drop_column("analytics_consent")
