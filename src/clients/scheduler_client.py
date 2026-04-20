"""Celery scheduler client — triggers background pipeline tasks."""
from __future__ import annotations

from src.core.logging.logger import get_logger


class SchedulerClient:
    """Wraps Celery task dispatch for pipeline triggering.

    Import celery app lazily to avoid circular imports at module load.
    """

    def __init__(self) -> None:
        self._logger = get_logger(__name__)

    def trigger_feature_engineering(self, run_date: str) -> str:
        """Dispatch feature_engineering_pipeline task. Returns task_id."""
        from src.worker import feature_engineering_task  # lazy import
        result = feature_engineering_task.delay(run_date=run_date)
        self._logger.info(
            "Feature engineering task dispatched",
            extra={"run_date": run_date, "task_id": result.id, "operation": "trigger"},
        )
        return result.id

    def trigger_batch_inference(self, run_date: str) -> str:
        """Dispatch batch_inference_pipeline task. Returns task_id."""
        from src.worker import batch_inference_task  # lazy import
        result = batch_inference_task.delay(run_date=run_date)
        self._logger.info(
            "Batch inference task dispatched",
            extra={"run_date": run_date, "task_id": result.id, "operation": "trigger"},
        )
        return result.id

    def trigger_training(self, run_date: str) -> str:
        """Dispatch training_pipeline task. Returns task_id."""
        from src.worker import training_task  # lazy import
        result = training_task.delay(run_date=run_date)
        self._logger.info(
            "Training task dispatched",
            extra={"run_date": run_date, "task_id": result.id, "operation": "trigger"},
        )
        return result.id
