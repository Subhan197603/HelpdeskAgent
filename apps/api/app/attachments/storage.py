"""Private S3-compatible attachment storage adapter."""

import asyncio
from collections.abc import Callable
from typing import Any, Protocol, TypeVar, cast

import boto3  # type: ignore[import-untyped]
from botocore.client import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from apps.api.app.core.settings import Settings

T = TypeVar("T")


class StorageError(Exception):
    """Object-store operation failed without exposing provider details."""


class ObjectTooLargeError(StorageError):
    """The quarantined object exceeds the authorized maximum."""


class ObjectStorage(Protocol):
    async def create_upload_url(
        self, key: str, content_type: str, size: int, checksum: str, expires: int
    ) -> str: ...

    async def read(self, key: str, maximum_bytes: int) -> bytes: ...

    async def promote(self, source: str, destination: str, content_type: str) -> None: ...

    async def reject(self, key: str) -> None: ...

    async def create_download_url(self, key: str, filename: str, expires: int) -> str: ...


class WritableObjectStorage(ObjectStorage, Protocol):
    async def write(self, key: str, content: bytes, content_type: str) -> None: ...

    async def copy(self, source: str, destination: str, content_type: str) -> None: ...


class S3ObjectStorage:
    """Use generated opaque keys in one private bucket; never trust client object paths."""

    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.object_storage_bucket
        self._encryption = settings.object_storage_server_side_encryption
        self._encryption_key = (
            settings.object_storage_sse_key_id.get_secret_value()
            if settings.object_storage_sse_key_id
            else None
        )
        access_key = (
            settings.object_storage_access_key.get_secret_value()
            if settings.object_storage_access_key
            else "not-configured"
        )
        secret_key = (
            settings.object_storage_secret_key.get_secret_value()
            if settings.object_storage_secret_key
            else "not-configured"
        )
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint,
            region_name=settings.object_storage_region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            use_ssl=settings.object_storage_use_ssl,
            config=Config(signature_version="s3v4"),
        )

    async def _call(self, operation: Callable[..., T], **kwargs: object) -> T:
        try:
            return await asyncio.to_thread(operation, **kwargs)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError("Object storage operation failed") from exc

    async def create_upload_url(
        self, key: str, content_type: str, size: int, checksum: str, expires: int
    ) -> str:
        parameters = {
            "Bucket": self._bucket,
            "Key": key,
            "ContentType": content_type,
            "ContentLength": size,
            "ACL": "private",
            "Metadata": {"expected-size": str(size), "expected-sha256": checksum},
        }
        if self._encryption is not None:
            parameters["ServerSideEncryption"] = self._encryption
        if self._encryption_key is not None:
            parameters["SSEKMSKeyId"] = self._encryption_key
        return cast(
            "str",
            await self._call(
                self._client.generate_presigned_url,
                ClientMethod="put_object",
                Params=parameters,
                ExpiresIn=expires,
                HttpMethod="PUT",
            ),
        )

    async def read(self, key: str, maximum_bytes: int) -> bytes:
        response = await self._call(self._client.get_object, Bucket=self._bucket, Key=key)
        declared = int(response.get("ContentLength", maximum_bytes + 1))
        if declared > maximum_bytes:
            raise ObjectTooLargeError("Stored object exceeds the permitted size")
        body = await asyncio.to_thread(response["Body"].read, maximum_bytes + 1)
        if len(body) > maximum_bytes:
            raise ObjectTooLargeError("Stored object exceeds the permitted size")
        return cast("bytes", body)

    async def write(self, key: str, content: bytes, content_type: str) -> None:
        parameters: dict[str, object] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": content,
            "ContentType": content_type,
            "ACL": "private",
        }
        if self._encryption is not None:
            parameters["ServerSideEncryption"] = self._encryption
        if self._encryption_key is not None:
            parameters["SSEKMSKeyId"] = self._encryption_key
        await self._call(self._client.put_object, **parameters)

    async def promote(self, source: str, destination: str, content_type: str) -> None:
        await self.copy(source, destination, content_type)
        await self._call(self._client.delete_object, Bucket=self._bucket, Key=source)

    async def copy(self, source: str, destination: str, content_type: str) -> None:
        parameters: dict[str, object] = {
            "Bucket": self._bucket,
            "Key": destination,
            "CopySource": {"Bucket": self._bucket, "Key": source},
            "MetadataDirective": "REPLACE",
            "ContentType": content_type,
        }
        if self._encryption is not None:
            parameters["ServerSideEncryption"] = self._encryption
        if self._encryption_key is not None:
            parameters["SSEKMSKeyId"] = self._encryption_key
        await self._call(
            self._client.copy_object,
            **parameters,
        )

    async def reject(self, key: str) -> None:
        await self._call(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def create_download_url(self, key: str, filename: str, expires: int) -> str:
        safe_name = filename.replace('"', "").replace("\r", "").replace("\n", "")
        return cast(
            "str",
            await self._call(
                self._client.generate_presigned_url,
                ClientMethod="get_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    "ResponseContentDisposition": f'attachment; filename="{safe_name}"',
                },
                ExpiresIn=expires,
                HttpMethod="GET",
            ),
        )
