"""Privacy-bounded first-party product analytics.

Only server-defined event names and properties are accepted. Player text,
generated prose, email, IP address and arbitrary client payloads never enter
this table.
"""

from __future__ import annotations

from typing import Any, Final, Literal

import sqlalchemy as sa

from apps.api.security import Principal
from database.models.platform import ProductEventORM
from database.repositories.sql import SqlUnitOfWork
from engine.core.ids import new_id

ProductEventName = Literal[
    "analytics_opted_in",
    "playthrough_started",
    "preview_started",
    "action_completed",
    "ending_selected",
    "project_created",
    "project_validated",
    "release_created",
]

_PROPERTY_ALLOWLIST: Final[dict[str, frozenset[str]]] = {
    "analytics_opted_in": frozenset(),
    "playthrough_started": frozenset({"scenario_key", "model_mode"}),
    "preview_started": frozenset({"scenario_key"}),
    "action_completed": frozenset({"turn_number", "steps", "degraded", "streamed"}),
    "ending_selected": frozenset({"ending_key", "ending_type"}),
    "project_created": frozenset({"template_key"}),
    "project_validated": frozenset({"valid", "error_count"}),
    "release_created": frozenset({"visibility"}),
}


def _safe_properties(event_name: str, supplied: dict[str, Any] | None) -> dict[str, Any]:
    allowed = _PROPERTY_ALLOWLIST[event_name]
    result: dict[str, Any] = {}
    for key, value in (supplied or {}).items():
        if key not in allowed:
            continue
        if isinstance(value, str):
            result[key] = value[:80]
        elif isinstance(value, (bool, int, float)) and not isinstance(value, complex):
            result[key] = value
    return result


async def record_product_event(
    uow: SqlUnitOfWork,
    principal: Principal,
    event_name: ProductEventName,
    *,
    playthrough_id: str | None = None,
    project_id: str | None = None,
    release_id: str | None = None,
    dedupe_key: str | None = None,
    properties: dict[str, Any] | None = None,
) -> bool:
    if not principal.analytics_consent:
        return False
    normalized_key = dedupe_key[:120] if dedupe_key else None
    if normalized_key is not None:
        existing = await uow.session.scalar(
            sa.select(ProductEventORM.id).where(
                ProductEventORM.user_id == principal.user_id,
                ProductEventORM.event_name == event_name,
                ProductEventORM.dedupe_key == normalized_key,
            )
        )
        if existing is not None:
            return False
    uow.session.add(
        ProductEventORM(
            id=new_id(),
            user_id=principal.user_id,
            event_name=event_name,
            dedupe_key=normalized_key,
            playthrough_id=playthrough_id,
            project_id=project_id,
            release_id=release_id,
            event_properties=_safe_properties(event_name, properties),
        )
    )
    return True
