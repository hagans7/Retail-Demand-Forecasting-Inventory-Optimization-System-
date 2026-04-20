"""Model registry repository — model_registry table."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions.app_exceptions import (
    ModelNotFoundError,
    ModelRegistrationError,
    NoProductionModelError,
    PersistenceError,
)
from src.core.logging.logger import get_logger
from src.db_models.model_registry_orm import ModelRegistryORM
from src.entities.model_version import ModelVersion
from src.interfaces.base_model_registry import BaseModelRegistry


class ModelRegistryRepository(BaseModelRegistry):
    """Reads and writes model_registry table."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session
        self._logger = get_logger(__name__)

    async def get_production_model(self) -> ModelVersion:
        result = await self._db.execute(
            select(ModelRegistryORM)
            .where(
                ModelRegistryORM.is_production == True,
                ModelRegistryORM.quantile_level == 0.60,
                ModelRegistryORM.archived == False,
            )
            .order_by(ModelRegistryORM.promoted_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise NoProductionModelError(
                "No production model registered. Run training pipeline."
            )
        return self._orm_to_entity(row)

    async def get_model_by_quantile(
        self, version_tag: str, quantile_level: float
    ) -> ModelVersion:
        result = await self._db.execute(
            select(ModelRegistryORM).where(
                ModelRegistryORM.version_tag == version_tag,
                ModelRegistryORM.quantile_level == quantile_level,
                ModelRegistryORM.archived == False,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise ModelNotFoundError(
                f"No model found for version_tag={version_tag}, q={quantile_level}"
            )
        return self._orm_to_entity(row)

    async def register_model(self, model: ModelVersion, artifact_path: str) -> str:
        try:
            row = ModelRegistryORM(
                version_id=model.version_id,
                version_tag=model.version_tag,
                quantile_level=model.quantile_level,
                algorithm=model.algorithm,
                features=model.features,
                target=model.target,
                loss=model.loss,
                best_iteration=model.best_iteration,
                trained_on_date=model.trained_on_date,
                val_mae=model.val_mae,
                val_mae_promo=model.val_mae_promo,
                val_uf_promo_pct=model.val_uf_promo_pct,
                naive_mae=model.naive_mae,
                artifact_path=artifact_path,
                training_data_start=model.training_data_start,
                training_data_end=model.training_data_end,
                training_data_rows=model.training_data_rows,
                training_seconds=model.training_seconds,
                training_data_hash=model.training_data_hash,
                is_production=False,
            )
            self._db.add(row)
            await self._db.commit()
            return model.version_id
        except Exception as e:
            await self._db.rollback()
            raise ModelRegistrationError(f"register_model failed: {e}") from e

    async def promote_to_production(self, version_id: str) -> None:
        row = await self._db.get(ModelRegistryORM, version_id)
        if row is None:
            raise ModelNotFoundError(f"version_id {version_id} not found")
        try:
            # Demote existing production for same quantile_level
            existing = await self._db.execute(
                select(ModelRegistryORM).where(
                    ModelRegistryORM.is_production == True,
                    ModelRegistryORM.quantile_level == row.quantile_level,
                )
            )
            for prev in existing.scalars().all():
                prev.is_production = False
            row.is_production = True
            row.promoted_at = datetime.now(tz=timezone.utc)
            await self._db.commit()
        except Exception as e:
            await self._db.rollback()
            raise PersistenceError(f"promote_to_production failed: {e}") from e

    async def get_models_for_archival(self, older_than_days: int) -> list[ModelVersion]:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=older_than_days)
        result = await self._db.execute(
            select(ModelRegistryORM).where(
                ModelRegistryORM.is_production == False,
                ModelRegistryORM.archived == False,
                ModelRegistryORM.created_at < cutoff,
            )
        )
        return [self._orm_to_entity(r) for r in result.scalars().all()]

    async def mark_as_archived(self, version_id: str) -> None:
        row = await self._db.get(ModelRegistryORM, version_id)
        if row:
            row.archived = True
            row.archived_at = datetime.now(tz=timezone.utc)
            row.artifact_path = None
            await self._db.commit()

    # ------------------------------------------------------------------
    def _orm_to_entity(self, row: ModelRegistryORM) -> ModelVersion:
        return ModelVersion(
            version_id=row.version_id,
            version_tag=row.version_tag,
            quantile_level=row.quantile_level,
            algorithm=row.algorithm,
            features=row.features if isinstance(row.features, list) else list(row.features),
            target=row.target,
            loss=row.loss,
            best_iteration=row.best_iteration,
            trained_on_date=row.trained_on_date,
            val_mae=row.val_mae,
            val_mae_promo=row.val_mae_promo,
            val_uf_promo_pct=row.val_uf_promo_pct,
            naive_mae=row.naive_mae,
            artifact_path=row.artifact_path,
            is_production=row.is_production,
            promoted_at=row.promoted_at,
            training_data_start=row.training_data_start,
            training_data_end=row.training_data_end,
            training_data_rows=row.training_data_rows or 0,
            training_seconds=row.training_seconds or 0.0,
            training_data_hash=row.training_data_hash,
            archived=row.archived,
            archived_at=row.archived_at,
        )
