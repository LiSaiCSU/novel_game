"""Object storage adapters for sanitized creator media."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from engine.core.config import Settings


class ObjectStore(Protocol):
    async def put(self, key: str, payload: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def check(self) -> None: ...
    async def delete(self, key: str) -> None: ...


class LocalObjectStore:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        target = (self.root / key).resolve()
        if self.root not in target.parents:
            raise ValueError("object key escapes storage root")
        return target

    async def put(self, key: str, payload: bytes, content_type: str) -> None:
        del content_type
        target = self._path(key)

        def write() -> None:
            # Keep directory creation and write in the same worker operation;
            # dev hot-reload/test cleanup cannot invalidate the parent between them.
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)

        await asyncio.to_thread(write)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def check(self) -> None:
        await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)

    async def delete(self, key: str) -> None:
        target = self._path(key)
        if target.is_file():
            await asyncio.to_thread(target.unlink)


class S3ObjectStore:
    def __init__(self, settings: Settings) -> None:
        import boto3

        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.s3_access_key or None,
            aws_secret_access_key=settings.s3_secret_key or None,
            region_name=settings.s3_region,
        )

    async def put(self, key: str, payload: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=payload,
            ContentType=content_type,
            # Draft assets are private. The authenticated media endpoint may add
            # public immutable caching only after an approved release references
            # the object.
            CacheControl="private, no-store",
        )

    async def get(self, key: str) -> bytes:
        try:
            response = await asyncio.to_thread(
                self.client.get_object, Bucket=self.bucket, Key=key
            )
        except Exception as exc:
            error = getattr(exc, "response", {}).get("Error", {})
            if str(error.get("Code", "")) in {"404", "NoSuchKey", "NotFound"}:
                raise FileNotFoundError(key) from exc
            raise
        body = response["Body"]
        try:
            return await asyncio.to_thread(body.read)
        finally:
            body.close()

    async def check(self) -> None:
        await asyncio.to_thread(self.client.head_bucket, Bucket=self.bucket)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)


@lru_cache(maxsize=8)
def _store(
    backend: str,
    assets_dir: str,
    endpoint: str,
    bucket: str,
    access_key: str,
    secret_key: str,
    region: str,
) -> ObjectStore:
    if backend == "s3":
        settings = Settings(
            object_store_backend=backend,
            assets_dir=assets_dir,
            s3_endpoint_url=endpoint,
            s3_bucket=bucket,
            s3_access_key=access_key,
            s3_secret_key=secret_key,
            s3_region=region,
        )
        return S3ObjectStore(settings)
    return LocalObjectStore(assets_dir)


def object_store(settings: Settings) -> ObjectStore:
    return _store(
        settings.object_store_backend,
        settings.assets_dir,
        settings.s3_endpoint_url,
        settings.s3_bucket,
        settings.s3_access_key,
        settings.s3_secret_key,
        settings.s3_region,
    )
