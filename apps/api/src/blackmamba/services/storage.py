"""Evidence object storage. Objects are write-once: `put` refuses to overwrite (FR-3)."""

import asyncio
import io
import os
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from minio import Minio
from minio.error import S3Error
from minio.sse import SseS3

from blackmamba.core.config import get_settings


class ObjectExistsError(Exception):
    pass


class ObjectMissingError(Exception):
    pass


class ObjectStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Store a new object. Raises ObjectExistsError if the key is taken."""

    async def get(self, key: str) -> bytes:
        """Raises ObjectMissingError."""


class MemoryStorage:
    """Tests/dev. `objects` is exposed so tests can simulate tampering."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        if key in self.objects:
            raise ObjectExistsError(key)
        self.objects[key] = (bytes(data), content_type)

    async def get(self, key: str) -> bytes:
        try:
            return self.objects[key][0]
        except KeyError as exc:
            raise ObjectMissingError(key) from exc


class LocalStorage:
    """Single-machine dev without MinIO. Files are created exclusively and made read-only."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("invalid key")
        return path

    def _put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
        except FileExistsError as exc:
            raise ObjectExistsError(key) from exc
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        path.chmod(0o444)

    def _get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise ObjectMissingError(key) from exc

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(self._put, key, data)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get, key)


class S3Storage:
    """MinIO / any S3 API. Every object is written with server-side encryption (NFR-1)."""

    def __init__(self, client: Minio, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    def _exists(self, key: str) -> bool:
        try:
            self.client.stat_object(self.bucket, key)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                return False
            raise
        return True

    def _put(self, key: str, data: bytes, content_type: str) -> None:
        if self._exists(key):
            raise ObjectExistsError(key)
        self.client.put_object(
            self.bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
            sse=SseS3(),
        )

    def _get(self, key: str) -> bytes:
        try:
            response = self.client.get_object(self.bucket, key)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                raise ObjectMissingError(key) from exc
            raise
        try:
            return bytes(response.read())
        finally:
            response.close()
            response.release_conn()

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(self._put, key, data, content_type)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get, key)


@lru_cache
def get_storage() -> ObjectStorage:
    settings = get_settings()
    if settings.storage_backend == "memory":
        return MemoryStorage()
    if settings.storage_backend == "local":
        return LocalStorage(settings.local_storage_path)
    endpoint = settings.s3_endpoint_url
    secure = endpoint.startswith("https://")
    host = endpoint.split("://", 1)[-1].rstrip("/")
    client = Minio(
        host,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key.get_secret_value(),
        secure=secure,
        region=settings.s3_region,
    )
    return S3Storage(client, settings.s3_bucket)
