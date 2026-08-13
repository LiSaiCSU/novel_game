"""ClamAV INSTREAM adapter for every user-controlled binary upload."""

from __future__ import annotations

import asyncio
import socket
import struct

from engine.core.config import Settings


class UploadMalwareDetected(ValueError):
    pass


class UploadScanUnavailable(RuntimeError):
    pass


def parse_clamav_response(response: bytes) -> None:
    text = response.rstrip(b"\0\r\n").decode("utf-8", errors="replace")
    if text.endswith(" OK"):
        return
    if text.endswith(" FOUND"):
        signature = text.rsplit(":", 1)[-1].removesuffix(" FOUND").strip()
        raise UploadMalwareDetected(signature or "malware signature detected")
    raise UploadScanUnavailable("malware scanner returned an invalid response")


def _scan_sync(settings: Settings, payload: bytes) -> None:
    try:
        with socket.create_connection(
            (settings.clamav_host, settings.clamav_port),
            timeout=settings.clamav_timeout_seconds,
        ) as connection:
            connection.settimeout(settings.clamav_timeout_seconds)
            connection.sendall(b"zINSTREAM\0")
            for start in range(0, len(payload), 64 * 1024):
                chunk = payload[start : start + 64 * 1024]
                connection.sendall(struct.pack(">I", len(chunk)) + chunk)
            connection.sendall(struct.pack(">I", 0))
            response = bytearray()
            while len(response) < 4096:
                part = connection.recv(4096 - len(response))
                if not part:
                    break
                response.extend(part)
                if b"\0" in part:
                    break
    except (OSError, TimeoutError) as exc:
        raise UploadScanUnavailable("malware scanner is unavailable") from exc
    parse_clamav_response(bytes(response))


async def scan_upload(settings: Settings, payload: bytes) -> None:
    if not settings.clamav_host:
        return
    await asyncio.to_thread(_scan_sync, settings, payload)
