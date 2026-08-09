"""FastAPI application entry point."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from apps.api.routers import debug, game, worlds
from database.session import create_all, dispose
from engine.core.config import get_settings
from engine.core.errors import EngineError
from engine.core.logging import bind, configure_logging, get_logger

logger = get_logger("api")
WEB_DIR = Path(__file__).resolve().parents[1] / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    # Dev convenience only; production schema management is Alembic's job.
    if settings.database_url.startswith("sqlite"):
        await create_all()
    logger.info(
        "world engine ready (pack=%s provider=%s)", settings.content_pack, settings.llm_provider
    )
    yield
    await dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI Narrative World Engine",
        version="0.1.0",
        description="An AI-native open-world text RPG engine. Content pack: cultivation_v1.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        bind(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(EngineError)
    async def engine_error_handler(_request: Request, exc: EngineError) -> JSONResponse:
        logger.warning("engine error: %s", exc.message)
        return JSONResponse(status_code=400, content=exc.to_dict())

    app.include_router(worlds.router, prefix="/api")
    app.include_router(game.router, prefix="/api")
    app.include_router(debug.router, prefix="/api")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "content_pack": settings.content_pack,
            "llm_provider": settings.llm_provider,
            "debug_mode": settings.debug_mode,
        }

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "apps.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.app_env == "dev",
    )


if __name__ == "__main__":
    main()
