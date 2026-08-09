"""Wiring. One place that knows how the whole engine is assembled."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.actions.intent_parser import IntentParser
from engine.characters.npc_agent import NPCAgent
from engine.contentpack.pack import ContentPack, load_content_pack
from engine.context.builder import ContextBuilder
from engine.core.config import Settings, get_settings
from engine.core.locks import InMemoryIdempotencyStore, InMemoryLockBackend
from engine.director.director import Director
from engine.knowledge.service import KnowledgeService
from engine.llm.client import LLMClient
from engine.llm.providers import build_provider
from engine.llm.router import ModelRouter
from engine.memory.embeddings import build_embedder
from engine.memory.extractor import MemoryExtractor
from engine.memory.retrieval import MemoryRetriever
from engine.narrative.renderer import NarrativeRenderer
from engine.orchestrator.orchestrator import GameOrchestrator, OrchestratorDeps
from engine.relationships.manager import RelationshipManager
from engine.rules.engine import RuleEngine
from engine.simulation.schedules import ScheduleService
from engine.simulation.simulator import WorldSimulator
from engine.world.consistency import ConsistencyGuard


def build_orchestrator(
    *,
    settings: Settings | None = None,
    pack: ContentPack | None = None,
    provider: Any | None = None,
    registry: Any | None = None,
) -> GameOrchestrator:
    settings = settings or get_settings()
    pack = pack or load_content_pack(settings.content_path, settings.content_pack)

    if registry is None:
        from prompts.registry import PromptRegistry

        registry = PromptRegistry(Path(settings.prompts_path))

    llm = LLMClient(
        provider if provider is not None else build_provider(settings),
        ModelRouter(settings),
        registry,
        max_retries=settings.llm_max_retries,
        max_repairs=settings.llm_max_repairs,
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
            min_interval_turns=settings.director_min_interval_turns,
        ),
        simulator=WorldSimulator(
            pack,
            ScheduleService(pack),
            knowledge,
            max_offline_minutes=settings.sim_max_offline_minutes,
        ),
        narrative=NarrativeRenderer(
            pack,
            context_builder,
            llm,
            registry,
            prompt_version=settings.prompt_version_narrative,
        ),
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
        llm=llm,
        locks=InMemoryLockBackend(),
        idempotency=InMemoryIdempotencyStore(),
        debug_mode=settings.debug_mode,
    )
    return GameOrchestrator(deps)
