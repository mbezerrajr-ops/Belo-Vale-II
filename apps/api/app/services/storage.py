from __future__ import annotations

import io
from functools import lru_cache
from typing import Protocol
from urllib.parse import urlsplit

from app.core.config import get_settings


class ObjectStorage(Protocol):
    def save(self, object_key: str, data: bytes, content_type: str) -> None: ...

    def load(self, object_key: str) -> bytes: ...


class InMemoryObjectStorage:
    """Test double; never used against production configuration."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def save(self, object_key: str, data: bytes, content_type: str) -> None:
        self.objects[object_key] = data

    def load(self, object_key: str) -> bytes:
        return self.objects[object_key]


class MinioObjectStorage:
    def __init__(
        self, *, endpoint: str, access_key: str, secret_key: str, bucket: str
    ) -> None:
        from minio import Minio

        parsed = urlsplit(endpoint)
        self._client = Minio(
            parsed.netloc,
            access_key=access_key,
            secret_key=secret_key,
            secure=parsed.scheme == "https",
        )
        self._bucket = bucket
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    def save(self, object_key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(
            self._bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    def load(self, object_key: str) -> bytes:
        response = self._client.get_object(self._bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()


@lru_cache
def get_object_storage() -> ObjectStorage:
    settings = get_settings()
    if not (settings.minio_url and settings.minio_access_key and settings.minio_secret_key):
        raise RuntimeError("MinIO configuration is required to store images")
    return MinioObjectStorage(
        endpoint=settings.minio_url,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket,
    )
