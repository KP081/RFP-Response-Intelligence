"""Object storage abstraction for S3-compatible storage (MinIO/S3)."""

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncGenerator, Optional

import aioboto3  # type: ignore[import-untyped]
from botocore.config import Config as BotoConfig  # type: ignore[import-untyped]

from app.core.settings import settings

if TYPE_CHECKING:
    from aiobotocore.client import AioBaseClient  # type: ignore[import-untyped]


@dataclass
class PresignedUrlResult:
    """Result of a presigned URL generation."""
    url: str
    expires_in: int


class ObjectStore(ABC):
    """Abstract interface for object storage operations."""

    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Upload an object to storage."""
        raise NotImplementedError

    @abstractmethod
    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> PresignedUrlResult:
        """Generate a presigned URL for downloading an object."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete an object from storage."""
        raise NotImplementedError


class S3ObjectStore(ObjectStore):
    """S3-compatible object store implementation using aioboto3."""

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        bucket: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ):
        self.endpoint_url = endpoint_url or settings.s3_endpoint
        self.bucket = bucket or settings.s3_bucket
        self.access_key = access_key or settings.s3_access_key
        self.secret_key = secret_key or settings.s3_secret_key

        if not self.bucket:
            raise ValueError("S3 bucket must be configured")

        self._session = aioboto3.Session(
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        )

        self._client_config = BotoConfig(
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
        )

    @asynccontextmanager
    async def _client(self) -> AsyncGenerator["AioBaseClient", None]:
        """Get an S3 client from the session."""
        async with self._session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            config=self._client_config,
        ) as client:
            yield client

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Upload an object to storage."""
        async with self._client() as client:
            await client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )

    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> PresignedUrlResult:
        """Generate a presigned URL for downloading an object."""
        async with self._client() as client:
            url = await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        return PresignedUrlResult(url=url, expires_in=expires_in)

    async def delete(self, key: str) -> None:
        """Delete an object from storage."""
        async with self._client() as client:
            await client.delete_object(Bucket=self.bucket, Key=key)


_object_store: Optional[ObjectStore] = None


def get_object_store() -> ObjectStore:
    """Get or create the global object store instance."""
    global _object_store
    if _object_store is None:
        _object_store = S3ObjectStore()
    return _object_store


def set_object_store(store: ObjectStore) -> None:
    """Set the global object store instance (useful for testing)."""
    global _object_store
    _object_store = store