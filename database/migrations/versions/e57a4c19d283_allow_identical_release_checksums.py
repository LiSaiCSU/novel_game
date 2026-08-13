"""allow identical release checksums across projects

Revision ID: e57a4c19d283
Revises: d41c82e7b5a0
Create Date: 2026-08-13 03:40:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e57a4c19d283"
down_revision: str | None = "d41c82e7b5a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_content_releases_checksum", table_name="content_releases")
    op.create_index(
        "ix_content_releases_checksum", "content_releases", ["checksum"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_content_releases_checksum", table_name="content_releases")
    op.create_index(
        "ix_content_releases_checksum", "content_releases", ["checksum"], unique=True
    )
