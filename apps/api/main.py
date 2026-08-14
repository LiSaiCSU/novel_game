"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import sqlalchemy as sa
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from apps.api.metrics import http_metrics
from apps.api.object_store import object_store
from apps.api.rate_limit import rate_limiter
from apps.api.routers import (
    admin,
    auth,
    catalog,
    creator,
    creator_assets,
    debug,
    game,
    gameplay,
    media,
    moderation,
    playthroughs,
    worlds,
)
from apps.api.routers import settings as user_settings
from database.bootstrap import ensure_official_releases
from database.session import create_all, dispose, get_sessionmaker
from engine.core.config import get_settings
from engine.core.errors import EngineError
from engine.core.logging import bind, configure_logging, get_logger

logger = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    # Dev convenience only; production schema management is Alembic's job.
    if settings.database_url.startswith("sqlite"):
        await create_all()
    await ensure_official_releases(settings, object_store(settings))
    logger.info(
        "world engine ready (pack=%s provider=%s)", settings.content_pack, settings.llm_provider
    )
    yield
    await rate_limiter.close()
    await dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.app_env,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            send_default_pii=False,
        )
    app = FastAPI(
        title="AI Narrative World Engine",
        version="0.2.0",
        description="Multi-user narrative game engine and Content Pack v2 creator platform.",
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
        started = time.perf_counter()
        http_metrics.start()
        status_code = 500
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        incoming_trace = request.headers.get("traceparent", "")
        match = re.fullmatch(r"[\da-f]{2}-([\da-f]{32})-[\da-f]{16}-[\da-f]{2}", incoming_trace)
        trace_id = match.group(1) if match else uuid.uuid4().hex
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        bind(request_id=request_id, trace_id=trace_id)
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            response.headers["traceparent"] = f"00-{trace_id}-{uuid.uuid4().hex[:16]}-01"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'"
            )
            response.headers["Server-Timing"] = (
                f"app;dur={(time.perf_counter() - started) * 1000:.1f}"
            )
            return response
        finally:
            route = getattr(request.scope.get("route"), "path", "unmatched")
            http_metrics.observe(
                request.method,
                route,
                status_code,
                time.perf_counter() - started,
            )

    @app.exception_handler(HTTPException)
    async def http_problem(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        title = (
            detail
            if isinstance(detail, str)
            else str(detail.get("message") or detail.get("code") or "request failed")
        )
        return JSONResponse(
            status_code=exc.status_code,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": title,
                "status": exc.status_code,
                "detail": detail,
                "instance": str(request.url.path),
            },
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_problem(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            media_type="application/problem+json",
            content={
                "type": "https://narrative.game/problems/validation",
                "title": "请求校验失败",
                "status": 422,
                "instance": str(request.url.path),
                "errors": exc.errors(),
            },
        )

    @app.exception_handler(EngineError)
    async def engine_error_handler(request: Request, exc: EngineError) -> JSONResponse:
        logger.warning("engine error: %s", exc.message)
        return JSONResponse(
            status_code=400,
            media_type="application/problem+json",
            content={
                "type": "https://narrative.game/problems/engine",
                "title": exc.message,
                "status": 400,
                "instance": str(request.url.path),
                **exc.to_dict(),
            },
        )

    # The pre-v1 contract has no tenant-aware identifiers. Keep it available
    # only for local migration tests; production exposes the owner-checked v1 API.
    if settings.debug_mode:
        app.include_router(worlds.router, prefix="/api")
        app.include_router(game.router, prefix="/api")
        app.include_router(debug.router, prefix="/api")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(creator.router, prefix="/api/v1")
    app.include_router(creator_assets.router, prefix="/api/v1")
    app.include_router(moderation.router, prefix="/api/v1")
    app.include_router(catalog.router, prefix="/api/v1")
    app.include_router(playthroughs.router, prefix="/api/v1")
    app.include_router(gameplay.router, prefix="/api/v1")
    app.include_router(user_settings.router, prefix="/api/v1")
    app.include_router(media.router)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "content_pack": settings.content_pack,
            "llm_provider": settings.llm_provider,
            "debug_mode": settings.debug_mode,
        }

    @app.get("/api/ready")
    async def ready() -> dict[str, str]:
        try:
            async with asyncio.timeout(3):
                maker = get_sessionmaker(settings)
                async with maker() as session:
                    await session.execute(sa.text("SELECT 1"))
                if settings.redis_url:
                    from redis.asyncio import from_url

                    redis = from_url(settings.redis_url, decode_responses=True)
                    try:
                        await redis.ping()
                    finally:
                        await redis.aclose()
                await object_store(settings).check()
        except Exception as exc:
            logger.error("readiness dependency failed: %s", type(exc).__name__)
            raise HTTPException(
                status_code=503, detail="service dependencies are not ready"
            ) from exc
        return {"status": "ready"}

    @app.get("/api/metrics", include_in_schema=False)
    async def metrics(request: Request) -> PlainTextResponse:
        if settings.metrics_token:
            supplied = request.headers.get("Authorization", "")
            expected = f"Bearer {settings.metrics_token}"
            if not secrets.compare_digest(supplied, expected):
                raise HTTPException(status_code=404, detail="not found")
        return PlainTextResponse(
            http_metrics.render(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

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
