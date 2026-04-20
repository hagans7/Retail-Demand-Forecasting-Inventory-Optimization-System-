"""MinIO storage client — only place in codebase that imports MinIO SDK.

Implements BaseStorageClient. Handles model artifacts and training JSON.

Retry policy: MAX_RETRIES=3, exponential backoff starting 2s.
All MinIO SDK exceptions normalized to StorageError or ModelNotFoundError.
"""
from __future__ import annotations

import asyncio
import io
import json
import random
import time
from typing import Any

from minio import Minio  # type: ignore[import]
from minio.error import S3Error  # type: ignore[import]

from src.core.config.settings import settings
from src.core.exceptions.app_exceptions import ModelNotFoundError, StorageError
from src.core.logging.logger import get_logger
from src.interfaces.base_storage_client import BaseStorageClient

MAX_RETRIES = 3


class MinIOStorageClient(BaseStorageClient):
    """MinIO-backed object storage for model artifacts and training JSON."""

    def __init__(self) -> None:
        self._client = Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self._bucket = settings.model_store_bucket
        self._logger = get_logger(__name__)
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        """Create bucket if it does not exist."""
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
                self._logger.info(
                    "MinIO bucket created",
                    extra={"bucket": self._bucket, "operation": "ensure_bucket"},
                )
        except S3Error as e:
            raise StorageError(f"MinIO bucket setup failed: {e}") from e

    def upload_model(self, version_id: str, booster_bytes: bytes) -> str:
        """Upload serialized LightGBM booster. Key: {version_id}/model.joblib"""
        key = f"{version_id}/model.joblib"
        return self._upload_bytes(key, booster_bytes, "application/octet-stream")

    def download_model(self, version_id: str) -> bytes:
        """Download serialized booster bytes."""
        key = f"{version_id}/model.joblib"
        return self._download_bytes(key, version_id=version_id)

    def upload_json(self, bucket: str, key: str, data: dict) -> str:
        """Upload JSON artifact. Used for training_artifacts.json."""
        payload = json.dumps(data, default=str).encode("utf-8")
        return self._upload_bytes(key, payload, "application/json", bucket=bucket)

    def download_json(self, bucket: str, key: str) -> dict:
        """Download and parse JSON artifact."""
        raw = self._download_bytes(key, bucket=bucket)
        return json.loads(raw.decode("utf-8"))

    def delete_model_artifacts(self, version_id: str) -> None:
        """Delete all objects under {version_id}/ prefix (archival cleanup)."""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                objects = self._client.list_objects(self._bucket, prefix=f"{version_id}/")
                for obj in objects:
                    self._client.remove_object(self._bucket, obj.object_name)
                self._logger.info(
                    "Model artifacts deleted",
                    extra={"version_id": version_id, "operation": "delete_artifacts"},
                )
                return
            except S3Error as e:
                self._logger.warning(
                    "Delete attempt failed",
                    extra={"attempt": attempt, "version_id": version_id},
                )
                if attempt == MAX_RETRIES:
                    raise StorageError(f"delete_model_artifacts failed: {e}") from e
                time.sleep(2 ** attempt + random.random())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _upload_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str,
        bucket: str | None = None,
    ) -> str:
        bucket = bucket or self._bucket
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._client.put_object(
                    bucket, key, io.BytesIO(data), len(data),
                    content_type=content_type,
                )
                self._logger.info(
                    "Artifact uploaded",
                    extra={"bucket": bucket, "key": key, "size_bytes": len(data),
                           "operation": "upload"},
                )
                return f"{bucket}/{key}"
            except S3Error as e:
                if attempt == MAX_RETRIES:
                    raise StorageError(f"upload failed for {key}: {e}") from e
                time.sleep(2 ** attempt + random.random())
        return ""  # unreachable

    def _download_bytes(
        self,
        key: str,
        bucket: str | None = None,
        version_id: str | None = None,
    ) -> bytes:
        bucket = bucket or self._bucket
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._client.get_object(bucket, key)
                data = response.read()
                response.close()
                return data
            except S3Error as e:
                if e.code == "NoSuchKey":
                    raise ModelNotFoundError(
                        f"Artifact not found: {bucket}/{key}"
                    ) from e
                if attempt == MAX_RETRIES:
                    raise StorageError(f"download failed for {key}: {e}") from e
                time.sleep(2 ** attempt + random.random())
        return b""  # unreachable

    def ensure_bucket(self, bucket_name: str) -> bool:
        """Create bucket if it does not exist. Returns True if created, False if existed."""
        try:
            if not self._client.bucket_exists(bucket_name):
                self._client.make_bucket(bucket_name)
                self._logger.info(
                    "MinIO bucket created",
                    extra={"bucket": bucket_name, "operation": "ensure_bucket"},
                )
                return True
            return False
        except S3Error as e:
            raise StorageError(f"ensure_bucket({bucket_name}) failed: {e}") from e

    def bucket_exists(self, bucket_name: str) -> bool:
        """Check if a bucket exists. Used by readiness checks."""
        try:
            return bool(self._client.bucket_exists(bucket_name))
        except S3Error:
            return False
