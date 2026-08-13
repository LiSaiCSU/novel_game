"""administrator TOTP step-up authentication

Revision ID: ca9102e4d731
Revises: b72e1d493af6
Create Date: 2026-08-13 05:40:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ca9102e4d731"
down_revision: str | None = "b72e1d493af6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("mfa_secret_encrypted", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("mfa_enabled_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("mfa_recovery_hashes", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("mfa_last_counter", sa.BigInteger(), nullable=True))
    with op.batch_alter_table("auth_sessions") as batch_op:
        batch_op.add_column(sa.Column("mfa_verified_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("auth_sessions") as batch_op:
        batch_op.drop_column("mfa_verified_at")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("mfa_last_counter")
        batch_op.drop_column("mfa_recovery_hashes")
        batch_op.drop_column("mfa_enabled_at")
        batch_op.drop_column("mfa_secret_encrypted")
