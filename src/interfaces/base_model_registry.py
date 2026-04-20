"""Abstract base for model registry."""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.entities.model_version import ModelVersion


class BaseModelRegistry(ABC):
    """Contract for model_registry table operations.

    Three versions registered per training run (q40, q60, q80).
    Only q60 with is_production=True is the active production model.
    """

    @abstractmethod
    async def get_production_model(self) -> ModelVersion:
        """Return active production model (q60, is_production=True).

        Raises:
            NoProductionModelError: If registry is empty or no promoted model.
        """

    @abstractmethod
    async def get_model_by_quantile(
        self,
        version_tag: str,
        quantile_level: float,
    ) -> ModelVersion:
        """Return a specific quantile model within a version_tag.

        Used by get_forecast_confidence to load q40/q80 alongside q60.

        Raises:
            ModelNotFoundError: If version_tag + quantile_level not found.
        """

    @abstractmethod
    async def register_model(
        self,
        model: ModelVersion,
        artifact_path: str,
    ) -> str:
        """Register a new model version. Returns assigned version_id.

        Does NOT automatically promote to production.

        Raises:
            ModelRegistrationError: On DB write failure.
        """

    @abstractmethod
    async def promote_to_production(self, version_id: str) -> None:
        """Set version_id as active production for its quantile_level.

        Demotes previous is_production=True model for same quantile_level.

        Raises:
            ModelNotFoundError: If version_id does not exist.
        """

    @abstractmethod
    async def get_models_for_archival(self, older_than_days: int) -> list[ModelVersion]:
        """Return non-production, non-archived models older than threshold."""

    @abstractmethod
    async def mark_as_archived(self, version_id: str) -> None:
        """Set archived=True, artifact_path=None. Keeps DB row for audit."""
