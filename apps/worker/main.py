"""Redis-backed maintenance worker for asynchronous platform jobs."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from apps.jobs import DEAD_LETTER_QUEUE, QUEUE
from apps.worker.tasks import (
    build_data_export,
    cleanup_expired_exports,
    cleanup_expired_previews,
    generate_asset_thumbnail,
    purge_due_accounts,
    run_email,
    scan_release,
)
from database.session import dispose
from engine.core.config import Settings, get_settings
from engine.core.logging import configure_logging, get_logger

logger = get_logger("worker")


async def dispatch(settings: Settings, job: dict[str, Any]) -> None:
    name = job.get("type")
    payload = dict(job.get("payload") or {})
    if name == "cleanup_expired_previews":
        logger.info("expired previews marked: %s", await cleanup_expired_previews(settings))
    elif name == "generate_asset_thumbnail":
        await generate_asset_thumbnail(
            settings, str(payload.get("asset_id", "")), str(payload.get("owner_id", ""))
        )
    elif name == "moderation_scan":
        problems = await scan_release(
            settings, str(payload.get("release_id", "")), str(payload.get("owner_id", ""))
        )
        logger.info("moderation scan completed: release=%s problems=%s", payload.get("release_id"), problems)
    elif name == "purge_due_accounts":
        logger.info("due accounts scrubbed: %s", await purge_due_accounts(settings))
    elif name == "send_email":
        await run_email(settings, payload)
    elif name == "build_data_export":
        await build_data_export(
            settings, str(payload.get("export_id", "")), str(payload.get("user_id", ""))
        )
    elif name == "cleanup_expired_exports":
        await cleanup_expired_exports(settings)
    else:
        raise ValueError(f"unknown background job: {name}")


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is required for the worker")
    from redis.asyncio import from_url

    redis = from_url(settings.redis_url, decode_responses=True)
    try:
        while True:
            item = await redis.blpop(QUEUE, timeout=30)
            if item:
                job = json.loads(item[1])
                try:
                    await dispatch(settings, job)
                except Exception:
                    attempt = int(job.get("attempt", 0)) + 1
                    job["attempt"] = attempt
                    logger.exception("background job failed: type=%s id=%s attempt=%s", job.get("type"), job.get("id"), attempt)
                    destination = QUEUE if attempt < 3 else DEAD_LETTER_QUEUE
                    await redis.rpush(destination, json.dumps(job, ensure_ascii=False))
            else:
                await cleanup_expired_previews(settings)
                await cleanup_expired_exports(settings)
                await purge_due_accounts(settings)
    finally:
        await redis.aclose()
        await dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
