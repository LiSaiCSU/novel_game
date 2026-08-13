"""Bounded JSON/YAML/ZIP decoding for untrusted creator packages."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import PurePosixPath
from typing import Any

import yaml
from fastapi import HTTPException
from yaml.events import AliasEvent

IMPORT_MAX_BYTES = 10 * 1024 * 1024
_MAX_EXPANDED_BYTES = 25 * 1024 * 1024
_MANIFEST_NAMES = {
    "package.json", "package.yaml", "package.yml",
    "content-pack.json", "content-pack.yaml", "content-pack.yml",
}


class _NoAliasSafeLoader(yaml.SafeLoader):
    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            raise yaml.YAMLError("YAML aliases are disabled for imported content")
        return super().compose_node(parent, index)


def _decode_document(raw: bytes, filename: str) -> dict[str, Any]:
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="content manifest exceeds the 2 MB limit")
    try:
        text = raw.decode("utf-8")
        value = json.loads(text) if filename.lower().endswith(".json") else yaml.load(
            text, Loader=_NoAliasSafeLoader
        )
    except (UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise HTTPException(status_code=422, detail="content manifest is not valid UTF-8 JSON/YAML") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail="content manifest must contain an object")
    return value


def import_document(raw: bytes, filename: str) -> dict[str, Any]:
    if not filename.lower().endswith(".zip"):
        return _decode_document(raw, filename)
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail="content archive is not a valid ZIP file") from exc
    with archive:
        files = [item for item in archive.infolist() if not item.is_dir()]
        if len(files) > 100:
            raise HTTPException(status_code=422, detail="content archive contains too many files")
        expanded = 0
        safe: dict[str, zipfile.ZipInfo] = {}
        for item in files:
            name = item.filename.replace("\\", "/")
            path = PurePosixPath(name)
            mode = (item.external_attr >> 16) & 0o170000
            if path.is_absolute() or ".." in path.parts or mode == 0o120000 or item.flag_bits & 1:
                raise HTTPException(status_code=422, detail="content archive contains an unsafe path")
            if item.file_size > IMPORT_MAX_BYTES:
                raise HTTPException(status_code=422, detail="content archive contains an oversized file")
            if item.file_size and item.file_size / max(item.compress_size, 1) > 100:
                raise HTTPException(status_code=422, detail="content archive compression ratio is unsafe")
            expanded += item.file_size
            safe[str(path)] = item
        if expanded > _MAX_EXPANDED_BYTES:
            raise HTTPException(status_code=422, detail="content archive expands beyond the 25 MB limit")
        manifests = [
            (name, info) for name, info in safe.items()
            if PurePosixPath(name).name.lower() in _MANIFEST_NAMES
        ]
        if len(manifests) != 1:
            raise HTTPException(status_code=422, detail="content archive must contain exactly one package manifest")
        manifest_name, manifest_info = manifests[0]
        document = _decode_document(archive.read(manifest_info), manifest_name)
        base = PurePosixPath(manifest_name).parent
        assets = ((document.get("manifest") or {}).get("assets") or [])
        for asset in assets:
            reference = str(base / str(asset.get("path", "")))
            if reference not in safe:
                raise HTTPException(status_code=422, detail=f"content archive is missing asset {asset.get('path')!r}")
        return document
