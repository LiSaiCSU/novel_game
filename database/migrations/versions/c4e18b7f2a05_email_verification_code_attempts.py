"""track failed attempts on email verification codes

A four digit code has a small keyspace, so the row itself has to be the
lockout boundary: the code burns after a handful of wrong guesses instead of
staying guessable until it expires.

Revision ID: c4e18b7f2a05
Revises: 31d7a52ce940
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e18b7f2a05"
down_revision: str | None = "31d7a52ce940"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("email_tokens") as batch_op:
        batch_op.add_column(
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0")
        )
    # Link tokens issued before the switch can never be redeemed by the code
    # form, and leaving them unused would block a fresh code for that user.
    op.execute(
        "UPDATE email_tokens SET used_at = CURRENT_TIMESTAMP "
        "WHERE purpose = 'verify_email' AND used_at IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("email_tokens") as batch_op:
        batch_op.drop_column("attempts")
