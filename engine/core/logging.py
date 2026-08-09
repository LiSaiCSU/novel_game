"""Structured logging. Debugging never relies on print (Prompt section 60)."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_turn_id: ContextVar[str] = ContextVar("turn_id", default="-")
_world_id: ContextVar[str] = ContextVar("world_id", default="-")
_session_id: ContextVar[str] = ContextVar("session_id", default="-")

_CONFIGURED = False


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        record.turn_id = _turn_id.get()
        record.world_id = _world_id.get()
        record.session_id = _session_id.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "turn_id": getattr(record, "turn_id", "-"),
            "world_id": getattr(record, "world_id", "-"),
            "session_id": getattr(record, "session_id", "-"),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", as_json: bool = False) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.addFilter(_ContextFilter())
    if as_json:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(levelname)-7s %(name)s [turn=%(turn_id)s] %(message)s")
        )
    root = logging.getLogger("aiworld")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"aiworld.{name}")


def bind(
    *,
    request_id: str | None = None,
    turn_id: str | None = None,
    world_id: str | None = None,
    session_id: str | None = None,
) -> None:
    if request_id is not None:
        _request_id.set(request_id)
    if turn_id is not None:
        _turn_id.set(turn_id)
    if world_id is not None:
        _world_id.set(world_id)
    if session_id is not None:
        _session_id.set(session_id)


def log_event(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    logger.log(level, message, extra={"extra_fields": fields})
