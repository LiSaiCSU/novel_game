"""Shared integration fixtures.

The app under test is assembled here rather than in one test module so every
integration module exercises the same wiring.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(monkeypatch, tmp_path, pack, registry):
    """A fully isolated app: its own database file, its own orchestrator, no LLM.

    Every seam the app uses to reach global state is redirected here, so a test
    run can never touch the developer's ./data/game.db.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import apps.api.deps as deps
    import database.session as db_session
    from apps.api.main import create_app
    from database.base import Base
    from engine.core.config import Settings
    from engine.orchestrator.factory import build_orchestrator

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'api.db').as_posix()}",
        llm_provider="null",
        debug_mode=True,
        embedding_dim=128,
        require_verified_email=False,
        auth_pepper="integration-test-pepper",
        credential_encryption_key="integration-test-credential-key",
        assets_dir=str(tmp_path / "assets"),
    )
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    # Routers may have captured these dependency callables during an earlier
    # test-module import. Keep their identities for FastAPI's override map.
    settings_dependency = deps.settings_dep
    orchestrator_dependency = deps.orchestrator_dep
    pack_dependency = deps.pack_dep

    # database.session is looked up by module global at call time
    monkeypatch.setattr(db_session, "get_engine", lambda *_a, **_k: engine)
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda *_a, **_k: maker)
    # apps.api.deps imported the name directly, so patch it there as well
    monkeypatch.setattr(deps, "get_sessionmaker", lambda *_a, **_k: maker)
    monkeypatch.setattr(deps, "settings_dep", lambda: settings)

    orchestrator = build_orchestrator(settings=settings, pack=pack, registry=registry)
    monkeypatch.setattr(deps, "orchestrator_dep", lambda: orchestrator)

    app = create_app()
    # dependency_overrides is the sanctioned seam for the Depends(...) defaults
    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[orchestrator_dependency] = lambda: orchestrator
    app.dependency_overrides[pack_dependency] = lambda: pack

    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as c,
        app.router.lifespan_context(app),
    ):
        yield c
    await engine.dispose()
