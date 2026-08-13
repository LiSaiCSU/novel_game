"""Application and PostgreSQL tenant enforcement helpers."""

from __future__ import annotations

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


async def set_tenant_context(session: AsyncSession, user_id: str) -> None:
    """Set the transaction-local identity consumed by PostgreSQL RLS policies."""
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        await session.execute(
            sa.text("SELECT set_config('app.current_user_id', :user_id, true)"),
            {"user_id": user_id},
        )


def require_owner(actual_owner_id: str, user_id: str) -> None:
    # Always return not-found to avoid confirming another tenant's identifiers.
    if actual_owner_id != user_id:
        raise HTTPException(status_code=404, detail="resource not found")
