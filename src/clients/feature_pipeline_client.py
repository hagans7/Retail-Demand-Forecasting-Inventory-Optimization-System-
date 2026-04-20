"""Feature pipeline client — triggers and monitors feature engineering."""
from __future__ import annotations

from src.core.logging.logger import get_logger


class FeaturePipelineClient:
    """Thin wrapper around feature pipeline task dispatch."""

    def __init__(self) -> None:
        self._logger = get_logger(__name__)

    def trigger(self, run_date: str) -> str:
        """Trigger feature engineering for run_date. Returns task_id."""
        from src.worker import feature_engineering_task  # lazy import
        result = feature_engineering_task.delay(run_date=run_date)
        return result.id
