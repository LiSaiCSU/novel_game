from __future__ import annotations

import io
import zipfile

import pytest
from fastapi import HTTPException

from apps.api.content_import import import_document
from apps.api.upload_scan import UploadMalwareDetected, UploadScanUnavailable, parse_clamav_response


def _zip(entries: dict[str, bytes], *, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return output.getvalue()


def test_import_rejects_path_traversal_archive() -> None:
    payload = _zip({"../package.json": b"{}"})

    with pytest.raises(HTTPException, match="unsafe path"):
        import_document(payload, "evil.zip")


def test_import_rejects_high_ratio_archive() -> None:
    payload = _zip({"package.json": b"{}", "huge.txt": b"0" * 1_000_000})

    with pytest.raises(HTTPException, match="compression ratio"):
        import_document(payload, "bomb.zip")


def test_import_rejects_yaml_aliases() -> None:
    payload = b"manifest: &manifest {title: Test}\ncopy: *manifest\n"

    with pytest.raises(HTTPException, match="valid UTF-8 JSON/YAML"):
        import_document(payload, "package.yaml")


def test_clamav_response_is_fail_closed() -> None:
    parse_clamav_response(b"stream: OK\0")
    with pytest.raises(UploadMalwareDetected, match="Eicar"):
        parse_clamav_response(b"stream: Eicar-Test-Signature FOUND\0")
    with pytest.raises(UploadScanUnavailable):
        parse_clamav_response(b"stream: size limit exceeded ERROR\0")
