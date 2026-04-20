"""Abstract base for decision simulation repository — V2."""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.entities.recommendation_object import RecommendationObject
from src.entities.decision_feedback_record import FeedbackStatus


class BaseDecisionRepository(ABC):
    """Contract for decision_simulations table.

    Audit trail for all V2 recommendations. config_snapshot is immutable after write.
    """

    @abstractmethod
    async def create_simulation(self, obj: RecommendationObject) -> str:
        """Persist recommendation. Returns simulation_id.

        config_snapshot is written once and never updated.

        Raises:
            PersistenceError: On DB write failure.
        """

    @abstractmethod
    async def get_simulation(self, simulation_id: str) -> RecommendationObject | None:
        """Return simulation by ID or None."""

    @abstractmethod
    async def get_pending_feedback(
        self,
        min_age_days: int,
        max_age_days: int,
    ) -> list[RecommendationObject]:
        """Return PENDING simulations created min_age to max_age days ago.

        Used by feedback_recalibration_pipeline.
        """

    @abstractmethod
    async def update_resolution(
        self,
        simulation_id: str,
        status: FeedbackStatus,
        actual_outcome: dict | None,
    ) -> None:
        """Set status + actual_outcome + resolved_at.

        Raises:
            SimulationNotFoundError: If simulation_id does not exist.
            PersistenceError: On DB write failure.
        """

    @abstractmethod
    async def get_simulation_drift_metrics(self, lookback_days: int) -> dict:
        """Aggregate drift metrics for monitoring dashboard.

        Returns:
            {
                "approval_success_rate": float,
                "roi_prediction_bias": float,
                "override_rate": float,
                "n_simulations": int,
                "n_resolved": int,
            }
        """
