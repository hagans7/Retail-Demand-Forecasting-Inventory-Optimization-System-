"""Abstract base for model client."""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd


class BaseModelClient(ABC):
    """Contract for LightGBM model loading and inference.

    Only clients/model_client.py implements this.
    Services type-hint against this interface — never against LlamaCppClient.
    """

    @abstractmethod
    def predict(
        self,
        X: pd.DataFrame,
        num_iteration: int | None = None,
    ) -> np.ndarray:
        """Generate raw predictions from the loaded model.

        Args:
            X: Feature matrix with columns matching INFERENCE_FEATURES.
            num_iteration: Number of trees to use. None = model best_iteration.

        Returns:
            1-D array of raw predictions, shape (n_rows,).

        Raises:
            ModelNotLoadedError: If no model has been loaded.
            PredictionError: If inference fails after MAX_RETRIES.
        """

    @abstractmethod
    def load_model(self, version_id: str, quantile_level: float = 0.60) -> None:
        """Load a specific model artifact from MinIO.

        Args:
            version_id: Registry version_id (e.g. "v1_20260401_q60").
            quantile_level: 0.40 | 0.60 | 0.80 — selects correct artifact path.

        Raises:
            ModelNotFoundError: If artifact does not exist in MinIO.
            StorageError: If MinIO connection fails.
        """

    @abstractmethod
    def get_loaded_version(self) -> str:
        """Return the version_id of the currently loaded model."""

    @abstractmethod
    def get_loaded_quantile(self) -> float:
        """Return the quantile_level of the currently loaded model."""
