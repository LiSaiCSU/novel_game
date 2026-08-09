"""SQLAlchemy foundations.

One declarative base and a JSON column type that becomes JSONB on PostgreSQL
and plain JSON on SQLite, so the same models serve both backends
(DECISIONS D-001).
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: JSONB where available, JSON elsewhere.
JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


def id_column() -> Mapped[str]:
    return mapped_column(sa.String(36), primary_key=True)


def fk(target: str, *, nullable: bool = True, index: bool = True) -> Mapped[str]:
    return mapped_column(
        sa.String(36), sa.ForeignKey(target, ondelete="CASCADE"), nullable=nullable, index=index
    )
