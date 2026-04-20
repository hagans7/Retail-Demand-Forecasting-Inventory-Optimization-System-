"""Training pipeline — manual trigger via POST /training/trigger."""
from __future__ import annotations
import asyncio
from datetime import date
from src.core.logging.logger import get_logger
_logger = get_logger(__name__)

async def run(run_date: str | None = None) -> dict:
    today = date.fromisoformat(run_date) if run_date else date.today()
    _logger.info("Training pipeline started",
                 extra={"run_date": str(today), "pipeline_name": "training"})
    from src.providers.infrastructure import _session_factory, get_storage_client
    from src.repositories.model_registry_repository import ModelRegistryRepository
    from src.repositories.feature_repository import FeatureRepository
    from src.services.train_model import TrainModelService

    storage = get_storage_client()
    async with _session_factory() as db:
        registry = ModelRegistryRepository(db)
        features = FeatureRepository(db)
        svc      = TrainModelService(features, registry, storage)
        result   = await svc.execute(str(today))

    _logger.info("Training pipeline complete",
                 extra={**{k:str(v) for k,v in result.items() if k!="results"},
                        "pipeline_name": "training"})
    return result

if __name__ == "__main__":
    asyncio.run(run())
