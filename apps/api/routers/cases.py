"""Deduction cases: start a run, make moves, talk freely, accuse."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from apps.api.deps import settings_dep, uow_dep
from apps.api.llm_config import load_platform_llm_settings
from apps.api.metrics import commerce_metrics
from apps.api.rate_limit import rate_limiter
from apps.api.runtime import (
    llm_cost_microunits,
    platform_tokens_available,
    release_runtime_service,
)
from apps.api.security import Principal, require_csrf, verified_principal
from apps.api.tenancy import set_tenant_context
from database.models.platform import CaseRunORM, UsageLedgerORM
from database.repositories.sql import SqlUnitOfWork
from engine.case.actor import interpret
from engine.case.engine import CaseEngine, Move, MoveRejected
from engine.case.library import load_cases
from engine.case.schema import CaseDefinition
from engine.case.state import CaseState
from engine.case.view import case_summary, case_view
from engine.core.config import Settings
from engine.core.errors import LLMError, StructuredOutputError
from engine.core.ids import new_id
from engine.core.logging import get_logger
from engine.llm.budget import BudgetedProvider
from engine.llm.client import LLMClient
from engine.llm.providers import build_provider
from engine.orchestrator.factory import build_llm_client

router = APIRouter(tags=["v1-cases"])
logger = get_logger("cases")

SAY_LIMIT_PER_MINUTE = 20


def _cases(settings: Settings) -> dict[str, CaseDefinition]:
    return load_cases(str(settings.content_path / "cases"))


def _engine(settings: Settings, key: str) -> CaseEngine:
    case = _cases(settings).get(key)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    return CaseEngine(case)


def _run_summary(row: CaseRunORM, case: CaseDefinition | None) -> dict[str, Any]:
    state = row.state or {}
    result = state.get("result") or {}
    return {
        "id": row.id,
        "case_key": row.case_key,
        "title": case.title if case else row.case_key,
        "status": row.status,
        "ending": row.ending,
        "ending_title": result.get("title"),
        "solved": bool(result.get("solved")),
        "route": result.get("route"),
        "grade": result.get("grade"),
        "minutes_left": state.get("minutes_left"),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _owned_run(uow: SqlUnitOfWork, run_id: str, user_id: str) -> CaseRunORM:
    row = await uow.session.scalar(
        sa.select(CaseRunORM).where(CaseRunORM.id == run_id, CaseRunORM.user_id == user_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="case run not found")
    return row


async def _discovered_routes(uow: SqlUnitOfWork, user_id: str, case_key: str) -> set[str]:
    """Winning routes this player has already found in this case, across runs."""
    rows = (
        await uow.session.scalars(
            sa.select(CaseRunORM.state).where(
                CaseRunORM.user_id == user_id,
                CaseRunORM.case_key == case_key,
                CaseRunORM.status == "closed",
            )
        )
    ).all()
    found: set[str] = set()
    for state in rows:
        result = (state or {}).get("result") or {}
        if result.get("solved") and result.get("route"):
            found.add(str(result["route"]))
    return found


async def _view(
    uow: SqlUnitOfWork, engine: CaseEngine, state: CaseState, user_id: str
) -> dict[str, Any]:
    discovered: set[str] = set()
    if engine.case.scheme is not None:
        discovered = await _discovered_routes(uow, user_id, engine.case.key)
    return case_view(engine, state, discovered)


def _save(row: CaseRunORM, state: CaseState) -> None:
    row.state = state.model_dump(mode="json")
    row.status = state.status
    row.ending = (state.result or {}).get("ending")
    row.updated_at = datetime.now(UTC)


def _rejected(exc: MoveRejected) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "case_move_rejected", "message": exc.message})


# ----------------------------------------------------------------------
@router.get("/cases")
async def list_cases(settings: Settings = Depends(settings_dep)) -> list[dict[str, Any]]:
    return [case_summary(case) for case in _cases(settings).values()]


@router.get("/case-runs")
async def my_runs(
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> list[dict[str, Any]]:
    await set_tenant_context(uow.session, principal.user_id)
    rows = (
        await uow.session.scalars(
            sa.select(CaseRunORM)
            .where(CaseRunORM.user_id == principal.user_id)
            .order_by(CaseRunORM.updated_at.desc())
            .limit(50)
        )
    ).all()
    cases = _cases(settings)
    return [_run_summary(row, cases.get(row.case_key)) for row in rows]


class StartRun(BaseModel):
    case_key: str = Field(min_length=1, max_length=80)


@router.post("/case-runs", status_code=201)
async def start_run(
    body: StartRun,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    await set_tenant_context(uow.session, principal.user_id)
    engine = _engine(settings, body.case_key)
    run_id = new_id()
    state = engine.new_state(seed=run_id)
    row = CaseRunORM(
        id=run_id,
        user_id=principal.user_id,
        case_key=engine.case.key,
        case_version=engine.case.version,
    )
    _save(row, state)
    uow.session.add(row)
    await uow.commit()
    return {"id": run_id, **(await _view(uow, engine, state, principal.user_id))}


@router.get("/case-runs/{run_id}")
async def get_run(
    run_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    await set_tenant_context(uow.session, principal.user_id)
    row = await _owned_run(uow, run_id, principal.user_id)
    engine = _engine(settings, row.case_key)
    state = CaseState.model_validate(row.state)
    return {"id": row.id, **(await _view(uow, engine, state, principal.user_id))}


@router.delete("/case-runs/{run_id}", status_code=204)
async def delete_run(
    run_id: str,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> None:
    await set_tenant_context(uow.session, principal.user_id)
    row = await _owned_run(uow, run_id, principal.user_id)
    await uow.session.delete(row)
    await uow.commit()


class CaseMove(BaseModel):
    kind: Literal["begin", "talk", "examine", "option", "present", "think", "accuse"]
    target: str | None = Field(default=None, max_length=80)
    evidence: str | None = Field(default=None, max_length=80)
    culprit: str | None = Field(default=None, max_length=80)
    weapon: str | None = Field(default=None, max_length=80)
    motive: str | None = Field(default=None, max_length=80)
    exhibits: list[str] = Field(default_factory=list, max_length=10)


@router.post("/case-runs/{run_id}/moves")
async def make_move(
    run_id: str,
    body: CaseMove,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    lock = release_runtime_service.infrastructure.lock_backend(settings)
    async with lock.acquire(f"case:{run_id}"):
        await set_tenant_context(uow.session, principal.user_id)
        row = await _owned_run(uow, run_id, principal.user_id)
        engine = _engine(settings, row.case_key)
        state = CaseState.model_validate(row.state)
        move = Move(
            kind=body.kind,
            target=body.target,
            evidence=body.evidence,
            culprit=body.culprit,
            weapon=body.weapon,
            motive=body.motive,
            exhibits=tuple(body.exhibits),
        )
        try:
            state = engine.apply(state, move)
        except MoveRejected as exc:
            raise _rejected(exc) from exc
        _save(row, state)
        await uow.commit()
        return {"id": row.id, **(await _view(uow, engine, state, principal.user_id))}


class CaseSay(BaseModel):
    character: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=200)


async def _platform_llm(uow: SqlUnitOfWork, settings: Settings, user_id: str) -> LLMClient:
    available = await platform_tokens_available(user_id, uow, settings)
    if available <= 0:
        raise HTTPException(
            status_code=429,
            detail={"code": "case_model_quota", "message": "platform inference quota exhausted"},
        )
    try:
        runtime_settings, _rows = await load_platform_llm_settings(uow.session, settings)
    except ValueError as exc:
        logger.error("platform model credential cannot be decrypted: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={"code": "case_model_unavailable", "message": "no model is configured"},
        ) from exc
    provider = BudgetedProvider(
        build_provider(runtime_settings), min(settings.llm_turn_token_limit, available)
    )
    llm = build_llm_client(runtime_settings, provider=provider)
    if not llm.available:
        raise HTTPException(
            status_code=503,
            detail={"code": "case_model_unavailable", "message": "no model is configured"},
        )
    return llm


def _record_usage(
    uow: SqlUnitOfWork, llm: LLMClient, settings: Settings, user_id: str
) -> None:
    for record in llm.records:
        cost = llm_cost_microunits(
            settings, record.provider, record.model, record.prompt_tokens, record.completion_tokens
        )
        billable = record.valid and not record.degraded
        uow.session.add(
            UsageLedgerORM(
                id=new_id(),
                user_id=user_id,
                playthrough_id=None,
                provider=record.provider,
                model=record.model,
                input_tokens=record.prompt_tokens,
                output_tokens=record.completion_tokens,
                cost_microunits=cost,
                success=billable,
            )
        )
        commerce_metrics.llm_usage(
            provider=record.provider,
            model=record.model,
            tokens=record.prompt_tokens + record.completion_tokens,
            cost_microunits=cost,
            success=billable,
        )


@router.post("/case-runs/{run_id}/say")
async def say(
    run_id: str,
    body: CaseSay,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    """Free text to one character. The model may pick a legal move or reply."""
    await rate_limiter.check(
        f"case-say:{principal.user_id}",
        SAY_LIMIT_PER_MINUTE,
        60,
        redis_url=settings.redis_url,
    )
    lock = release_runtime_service.infrastructure.lock_backend(settings)
    async with lock.acquire(f"case:{run_id}"):
        await set_tenant_context(uow.session, principal.user_id)
        row = await _owned_run(uow, run_id, principal.user_id)
        engine = _engine(settings, row.case_key)
        state = CaseState.model_validate(row.state)
        if state.status != "active":
            raise _rejected(MoveRejected("free questions are only possible during the investigation"))
        llm = await _platform_llm(uow, settings, principal.user_id)
        try:
            move = await interpret(llm, engine, state, body.character, body.text)
            state = engine.apply(state, move)
        except MoveRejected as exc:
            _record_usage(uow, llm, settings, principal.user_id)
            await uow.commit()
            raise _rejected(exc) from exc
        except (LLMError, StructuredOutputError) as exc:
            logger.warning("case actor failed run=%s: %s", run_id, exc)
            _record_usage(uow, llm, settings, principal.user_id)
            await uow.commit()
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "case_actor_failed",
                    "message": "the character could not answer right now",
                },
            ) from exc
        _record_usage(uow, llm, settings, principal.user_id)
        _save(row, state)
        await uow.commit()
        return {
            "id": row.id,
            "interpreted_as": move.kind,
            **(await _view(uow, engine, state, principal.user_id)),
        }
