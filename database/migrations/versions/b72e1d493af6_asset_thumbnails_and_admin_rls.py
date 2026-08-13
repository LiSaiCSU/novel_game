"""asset thumbnails and administrator usage visibility

Revision ID: b72e1d493af6
Revises: f18b7d2ac604
Create Date: 2026-08-13 05:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b72e1d493af6"
down_revision: str | None = "f18b7d2ac604"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("assets") as batch_op:
        batch_op.add_column(sa.Column("thumbnail_object_key", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("thumbnail_width", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("thumbnail_height", sa.Integer(), nullable=True))
        batch_op.create_unique_constraint(
            "uq_assets_thumbnail_object_key", ["thumbnail_object_key"]
        )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                "CREATE POLICY usage_ledger_admin_read_policy ON usage_ledger FOR SELECT "
                "USING (EXISTS (SELECT 1 FROM user_roles ur "
                "WHERE ur.user_id = NULLIF(current_setting('app.current_user_id', true), '') "
                "AND ur.role = 'admin'))"
            )
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text("DROP POLICY IF EXISTS usage_ledger_admin_read_policy ON usage_ledger")
        )
    with op.batch_alter_table("assets") as batch_op:
        batch_op.drop_constraint("uq_assets_thumbnail_object_key", type_="unique")
        batch_op.drop_column("thumbnail_height")
        batch_op.drop_column("thumbnail_width")
        batch_op.drop_column("thumbnail_object_key")
