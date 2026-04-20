"""LightGBM model client — only place in codebase that imports lightgbm.

Implements BaseModelClient. Loads model artifacts from MinIO via storage_client.
Models cached per (version_id, quantile_level) — reloaded only when changed.

CRITICAL: numpy must be <2.0 (lgbm 4.6 breaks at predict() with numpy 2.x).
"""
from __future__ import annotations

import io
import random
import time

import joblib  # type: ignore[import]
import lightgbm as lgb  # type: ignore[import]
import numpy as np
import pandas as pd

from src.core.exceptions.app_exceptions import (
    ModelNotFoundError,
    ModelNotLoadedError,
    PredictionError,
)
from src.core.logging.logger import get_logger
from src.interfaces.base_model_client import BaseModelClient
from src.interfaces.base_storage_client import BaseStorageClient

MAX_RETRIES = 3


class LightGBMModelClient(BaseModelClient):
    """Singleton-safe LightGBM model client with in-process artifact caching.

    One instance per worker process (via @lru_cache in providers/infrastructure.py).
    Loaded model persists for the lifetime of the worker process.
    """

    def __init__(self, storage_client: BaseStorageClient) -> None:
        self._storage = storage_client
        self._booster: lgb.Booster | None = None
        self._loaded_version: str = ""
        self._loaded_quantile: float = 0.0
        self._logger = get_logger(__name__)

    def predict(
        self,
        X: pd.DataFrame,
        num_iteration: int | None = None,
    ) -> np.ndarray:
        """Run inference. num_iteration defaults to model best_iteration."""
        if self._booster is None:
            raise ModelNotLoadedError("No model loaded. Call load_model() first.")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                raw = self._booster.predict(
                    X.values,
                    num_iteration=num_iteration,
                )
                return np.asarray(raw, dtype=np.float64)
            except Exception as e:
                self._logger.warning(
                    "Prediction attempt failed",
                    extra={
                        "attempt": attempt,
                        "model_version": self._loaded_version,
                        "error_type": type(e).__name__,
                        "operation": "predict",
                    },
                )
                if attempt == MAX_RETRIES:
                    raise PredictionError(
                        f"Model inference failed after {MAX_RETRIES} retries: {e}"
                    ) from e
                time.sleep(2 ** attempt + random.random())
        return np.array([])  # unreachable

    def load_model(self, version_id: str, quantile_level: float = 0.60) -> None:
        """Load model artifact from MinIO. Skips reload if already loaded."""
        if (
            self._loaded_version == version_id
            and abs(self._loaded_quantile - quantile_level) < 1e-6
        ):
            return  # already loaded — skip expensive reload

        self._logger.info(
            "Loading model artifact",
            extra={
                "version_id": version_id,
                "quantile_level": quantile_level,
                "operation": "load_model",
            },
        )
        try:
            artifact_bytes = self._storage.download_model(version_id)
            self._booster = joblib.load(io.BytesIO(artifact_bytes))
            self._loaded_version = version_id
            self._loaded_quantile = quantile_level
            self._logger.info(
                "Model loaded successfully",
                extra={
                    "version_id": version_id,
                    "quantile_level": quantile_level,
                    "operation": "load_model",
                },
            )
        except ModelNotFoundError:
            raise
        except Exception as e:
            raise ModelNotFoundError(
                f"Failed to load model {version_id}: {e}"
            ) from e

    def get_loaded_version(self) -> str:
        return self._loaded_version

    def get_loaded_quantile(self) -> float:
        return self._loaded_quantile
