"""Wiring. One place that knows how the whole engine is assembled."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.actions.autopilot import Autopilot
from engine.actions.intent_parser import IntentParser
from engine.characters.npc_agent import NPCAgent
from engine.contentpack.pack import ContentPack, load_content_pack
from engine.context.builder import ContextBuilder
from engine.core.config import Settings, get_settings
from engine.core.locks import (
    IdempotencyStore,
    InMemoryIdempotencyStore,
    InMemoryLockBackend,
    LockBackend,
)
from engine.core.types import LLMRole
from engine.director.director import Director
from engine.director.plot_steward import PlotSteward
from engine.knowledge.service import KnowledgeService
from engine.llm.client import LLMClient
from engine.llm.providers import build_provider
from engine.llm.router import ModelRouter
from engine.memory.embeddings import build_embedder
from engine.memory.extractor import MemoryExtractor
from engine.memory.retrieval import MemoryRetriever
from engine.narrative.chapter import ChapterRenderer
from engine.narrative.prologue import Prologue
from engine.narrative.renderer import NarrativeRenderer
from engine.orchestrator.interrupt import InterruptDetector
from engine.orchestrator.orchestrator import GameOrchestrator, OrchestratorDeps
from engine.relationships.manager import RelationshipManager
from engine.rules.engine import RuleEngine
from engine.simulation.schedules import ScheduleService
from engine.simulation.simulator import WorldSimulator
from engine.world.consistency import ConsistencyGuard
from engine.world.steward import WorldSteward


def _extra_body(settings: Settings, attribute: str = "llm_extra_body") -> dict[str, Any]:
    """Vendor request-body switches, parsed from configuration only."""
    raw = (getattr(settings, attribute, "") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{attribute.upper()} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{attribute.upper()} must be a JSON object")
    return parsed


def build_orchestrator(
    *,
    settings: Settings | None = None,
    pack: ContentPack | None = None,
    provider: Any | None = None,
    registry: Any | None = None,
    lock_backend: LockBackend | None = None,
    idempotency_store: IdempotencyStore | None = None,
) -> GameOrchestrator:
    settings = settings or get_settings()
    pack = pack or load_content_pack(settings.content_path, settings.content_pack)

    if registry is None:
        from prompts.registry import PromptRegistry

        registry = PromptRegistry(Path(settings.prompts_path))

    narrative_extra_body = _extra_body(settings)
    reasoning_extra_body = (
        _extra_body(settings, "llm_reasoning_extra_body")
        if settings.llm_reasoning_extra_body.strip()
        else narrative_extra_body
    )
    llm = LLMClient(
        provider if provider is not None else build_provider(settings),
        ModelRouter(settings),
        registry,
        max_retries=settings.llm_max_retries,
        max_repairs=settings.llm_max_repairs,
        extra_body=narrative_extra_body,
        extra_body_by_role={
            role: reasoning_extra_body
            for role in (
                LLMRole.INTENT,
                LLMRole.NPC,
                LLMRole.NPC_MAJOR,
                LLMRole.DIRECTOR,
                LLMRole.STEWARD,
                LLMRole.MEMORY,
            )
        },
        truncation_retries=settings.llm_truncation_retries,
    )

    embedder = build_embedder(settings)
    knowledge = KnowledgeService(pack)
    retriever = MemoryRetriever(pack, embedder)
    context_builder = ContextBuilder(
        pack,
        knowledge,
        retriever,
        embedder,
        budgets={
            "intent": settings.ctx_budget_intent,
            "npc": settings.ctx_budget_npc,
            "director": settings.ctx_budget_director,
            "narrative": settings.ctx_budget_narrative,
            "memory": settings.ctx_budget_memory,
        },
    )

    narrative = NarrativeRenderer(
        pack,
        context_builder,
        llm,
        registry,
        prompt_version=settings.prompt_version_narrative,
    )

    deps = OrchestratorDeps(
        pack=pack,
        rules=RuleEngine(),
        intent_parser=IntentParser(
            pack,
            context_builder,
            llm,
            registry,
            prompt_version=settings.prompt_version_player_intent,
        ),
        context_builder=context_builder,
        knowledge=knowledge,
        npc_agent=NPCAgent(
            pack,
            knowledge,
            context_builder,
            llm,
            registry,
            prompt_version=settings.prompt_version_npc_decision,
        ),
        director=Director(
            pack,
            context_builder,
            llm,
            registry,
            prompt_version=settings.prompt_version_director,
            # None lets the pack decide; a positive setting overrides it.
            min_interval_turns=settings.director_min_interval_turns or None,
        ),
        simulator=WorldSimulator(
            pack,
            ScheduleService(pack),
            knowledge,
            max_offline_minutes=settings.sim_max_offline_minutes,
        ),
        narrative=narrative,
        chapter=ChapterRenderer(
            pack,
            context_builder,
            narrative,
            llm,
            registry,
            prompt_version=settings.prompt_version_chapter,
        ),
        interrupts=InterruptDetector(pack),
        memory=MemoryExtractor(
            pack,
            context_builder,
            embedder,
            llm,
            registry,
            prompt_version=settings.prompt_version_memory_extractor,
        ),
        relationships=RelationshipManager(pack),
        guard=ConsistencyGuard(pack),
        steward=WorldSteward(
            pack, llm, registry, prompt_version=settings.prompt_version_world_steward
        ),
        plot_steward=PlotSteward(
            pack, llm, registry, prompt_version=settings.prompt_version_plot_steward
        ),
        autopilot=Autopilot(
            pack, llm, registry, prompt_version=settings.prompt_version_autopilot
        ),
        prologue=Prologue(
            pack,
            context_builder,
            llm,
            registry,
            prompt_version=settings.prompt_version_prologue,
        ),
        llm=llm,
        locks=lock_backend or InMemoryLockBackend(),
        idempotency=idempotency_store or InMemoryIdempotencyStore(),
        debug_mode=settings.debug_mode,
    )
    return GameOrchestrator(deps)
