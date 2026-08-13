"""Shared ownership lookup used by creator-facing route modules."""

from __future__ import annotations

from fastapi import HTTPException

from apps.api.tenancy import require_owner
from database.models.platform import ProjectORM
from database.repositories.sql import SqlUnitOfWork


async def owned_project(
    uow: SqlUnitOfWork,
    project_id: str,
    user_id: str,
) -> ProjectORM:
    row = await uow.session.get(ProjectORM, project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
    require_owner(row.owner_id, user_id)
    return row
