"""Abstract base for object storage client (MinIO)."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseStorageClient(ABC):
    """Contract for MinIO model artifact storage.

    Only clients/storage_client.py imports the MinIO SDK.
    """

    @abstractmethod
    def upload_model(self, version_id: str, booster_bytes: bytes) -> str:
        """Upload serialized LightGBM booster. Returns artifact path.

        Raises:
            StorageError: On MinIO connection or write failure.
        """

    @abstractmethod
    def download_model(self, version_id: str) -> bytes:
        """Download serialized LightGBM booster bytes.

        Raises:
            ModelNotFoundError: If artifact does not exist.
            StorageError: On MinIO connection failure.
        """

    @abstractmethod
    def upload_json(self, bucket: str, key: str, data: dict) -> str:
        """Upload JSON artifact (training_artifacts.json). Returns object path.

        Used by train_model to persist feature importance and reference distributions
        for compute_feature_drift to use as PSI baseline.
        """

    @abstractmethod
    def download_json(self, bucket: str, key: str) -> dict:
        """Download and parse JSON artifact.

        Raises:
            StorageError: On MinIO connection failure or missing key.
        """

    @abstractmethod
    def delete_model_artifacts(self, version_id: str) -> None:
        """Delete all objects under bucket/{version_id}/ prefix.

        Used by model_challenger_pipeline for archival cleanup after MODEL_ARCHIVAL_DAYS.
        Raises:
            StorageError: On MinIO failure.
        """
