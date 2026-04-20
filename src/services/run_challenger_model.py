"""Run challenger model service — monthly champion vs challenger evaluation."""
from __future__ import annotations

from src.core.constants.model_constants import MODEL_ARCHIVAL_DAYS
from src.core.logging.logger import get_logger
from src.interfaces.base_model_registry import BaseModelRegistry
from src.interfaces.base_storage_client import BaseStorageClient


class RunChallengerModelService:
    """Evaluates challenger against champion. Promotes if beats by threshold.

    Also performs archival cleanup: deletes MinIO artifacts for non-production
    models older than MODEL_ARCHIVAL_DAYS (90 days). DB row is retained.
    """

    def __init__(
        self,
        model_registry: BaseModelRegistry,
        storage_client: BaseStorageClient,
        train_service,
    ) -> None:
        self._registry = model_registry
        self._storage  = storage_client
        self._trainer  = train_service
        self._logger   = get_logger(__name__)

    async def execute(self, run_date: str | None = None) -> dict:
        self._logger.info("Challenger model pipeline started",
                          extra={"run_date": run_date, "operation": "run_challenger_model"})

        # 1. Train challenger
        result = await self._trainer.execute(run_date=run_date)
        promoted = result.get("promoted", False)

        # 2. Archive old non-production models
        old_models = await self._registry.get_models_for_archival(MODEL_ARCHIVAL_DAYS)
        archived   = 0
        for model in old_models:
            try:
                self._storage.delete_model_artifacts(model.version_id)
                await self._registry.mark_as_archived(model.version_id)
                archived += 1
            except Exception as e:
                self._logger.warning(f"Archival failed for {model.version_id}: {e}")

        self._logger.info(
            "Challenger pipeline complete",
            extra={"promoted": promoted, "archived": archived,
                   "operation": "run_challenger_model"},
        )
        return {"promoted": promoted, "archived": archived, **result}
