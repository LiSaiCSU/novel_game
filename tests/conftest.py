from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from database.memory_uow import MemoryStore, MemoryUnitOfWork  # noqa: E402
from engine.contentpack.pack import ContentPack, load_content_pack  # noqa: E402
from engine.core.ids import PLAYER_KEY  # noqa: E402
from engine.rng.game_rng import GameRNG, session_rng  # noqa: E402
from engine.rules.base import RuleContext  # noqa: E402
from engine.world.seeder import PlayerSpec, SeedBundle, build_world  # noqa: E402
from engine.world.state_view import WorldStateView, build_world_state  # noqa: E402

PACK_KEY = "cultivation_v1"
CONTENT_DIR = REPO_ROOT / "content"


@pytest.fixture(scope="session")
def pack() -> ContentPack:
    return load_content_pack(CONTENT_DIR, PACK_KEY)


@pytest.fixture
def player_spec() -> PlayerSpec:
    return PlayerSpec(name="测试者", gender="male", age=18, background="外门新入弟子")


@pytest.fixture
def bundle(pack: ContentPack, player_spec: PlayerSpec) -> SeedBundle:
    return build_world(pack, world_seed="test-seed", player=player_spec)


@pytest.fixture
def store(bundle: SeedBundle) -> MemoryStore:
    s = MemoryStore()
    s.load(bundle)
    return s


@pytest.fixture
def uow(store: MemoryStore) -> MemoryUnitOfWork:
    return MemoryUnitOfWork(store)


@pytest.fixture
def player_id(bundle: SeedBundle) -> str:
    player = bundle.character_by_key(PLAYER_KEY)
    assert player is not None
    return player.id


@pytest.fixture
async def state(
    uow: MemoryUnitOfWork, pack: ContentPack, bundle: SeedBundle, player_id: str
) -> WorldStateView:
    return await build_world_state(uow, pack, bundle.world.id, player_id)


@pytest.fixture
def rng(bundle: SeedBundle) -> GameRNG:
    return session_rng(bundle.world.world_seed, "test-session")


@pytest.fixture
def ctx(pack: ContentPack, state: WorldStateView, rng: GameRNG) -> RuleContext:
    return RuleContext(pack=pack, state=state, rng=rng)


# --- AI-layer fixtures (all deterministic; no network) ----------------------
@pytest.fixture
def embedder():
    from engine.memory.embeddings import HashEmbedder

    return HashEmbedder(dimension=128)


@pytest.fixture
def knowledge_service(pack: ContentPack):
    from engine.knowledge.service import KnowledgeService

    return KnowledgeService(pack)


@pytest.fixture
def retriever(pack: ContentPack, embedder):
    from engine.memory.retrieval import MemoryRetriever

    return MemoryRetriever(pack, embedder)


@pytest.fixture
def context_builder(pack: ContentPack, knowledge_service, retriever, embedder):
    from engine.context.builder import ContextBuilder

    return ContextBuilder(pack, knowledge_service, retriever, embedder)


@pytest.fixture
def npc_agent(pack: ContentPack, knowledge_service, context_builder):
    from engine.characters.npc_agent import NPCAgent

    return NPCAgent(pack, knowledge_service, context_builder)


@pytest.fixture
def registry():
    from prompts.registry import PromptRegistry

    return PromptRegistry(REPO_ROOT / "prompts")


# --- orchestrator ----------------------------------------------------------
@pytest.fixture
def settings():
    """Deterministic settings: no provider, no network, tiny embeddings."""
    from engine.core.config import Settings

    return Settings(
        llm_provider="null",
        debug_mode=True,
        embedding_backend="hash",
        embedding_dim=128,
        content_dir=str(CONTENT_DIR),
        content_pack=PACK_KEY,
        prompts_dir=str(REPO_ROOT / "prompts"),
    )


@pytest.fixture
def orchestrator(settings, pack: ContentPack, registry):
    from engine.orchestrator.factory import build_orchestrator

    return build_orchestrator(settings=settings, pack=pack, registry=registry)


@pytest.fixture
def session_id(bundle: SeedBundle) -> str:
    assert bundle.session is not None
    return bundle.session.id
