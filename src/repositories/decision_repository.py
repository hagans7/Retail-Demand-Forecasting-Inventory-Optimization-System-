"""Decision repository — decision_simulations table CRUD.

Immutable audit trail: config_snapshot written once at create; never updated.
actual_outcome filled by feedback_recalibration_pipeline.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions.app_exceptions import PersistenceError, SimulationNotFoundError
from src.core.logging.logger import get_logger
from src.db_models.decision_orm import DecisionSimulationORM
from src.entities.decision_feedback_record import FeedbackStatus
from src.entities.recommendation_object import DecisionState, RecommendationObject
from src.interfaces.base_decision_repository import BaseDecisionRepository


class DecisionRepository(BaseDecisionRepository):
    """CRUD for decision_simulations table."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session
        self._logger = get_logger(__name__)

    async def create_simulation(self, obj: RecommendationObject) -> str:
        sim_id = obj.simulation_id or str(uuid.uuid4())
        try:
            row = DecisionSimulationORM(
                simulation_id=sim_id,
                store_id=obj.store_id,
                item_id=obj.item_id,
                recommendation=obj.recommendation.value,
                decision_score=obj.decision_score,
                predicted_roi=obj.net_roi_pct,
                probability_profitable=obj.probability_profitable,
                uncertainty_band=obj.uncertainty_band,
                risk_notes=obj.risk_notes,
                recommended_action=obj.recommended_action,
                config_snapshot=obj.config_snapshot,   # frozen at creation
                predicted_uplift_pct=obj.expected_uplift_pct,
                status="PENDING",
                override_flag=False,
            )
            self._db.add(row)
            await self._db.commit()
            self._logger.info(
                "Simulation created",
                extra={
                    "simulation_id": sim_id,
                    "recommendation": obj.recommendation.value,
                    "decision_score": obj.decision_score,
                    "operation": "create_simulation",
                },
            )
            return sim_id
        except Exception as e:
            await self._db.rollback()
            raise PersistenceError(f"create_simulation failed: {e}") from e

    async def get_simulation(self, simulation_id: str) -> RecommendationObject | None:
        row = await self._db.get(DecisionSimulationORM, simulation_id)
        return self._orm_to_entity(row) if row else None

    async def get_pending_feedback(
        self,
        min_age_days: int,
        max_age_days: int,
    ) -> list[RecommendationObject]:
        now = datetime.now(tz=timezone.utc)
        min_created = now - timedelta(days=max_age_days)
        max_created = now - timedelta(days=min_age_days)
        result = await self._db.execute(
            select(DecisionSimulationORM).where(
                DecisionSimulationORM.status == "PENDING",
                DecisionSimulationORM.created_at >= min_created,
                DecisionSimulationORM.created_at <= max_created,
            )
        )
        rows = result.scalars().all()
        return [self._orm_to_entity(r) for r in rows]

    async def update_resolution(
        self,
        simulation_id: str,
        status: FeedbackStatus,
        actual_outcome: dict | None,
    ) -> None:
        row = await self._db.get(DecisionSimulationORM, simulation_id)
        if row is None:
            raise SimulationNotFoundError(f"Simulation {simulation_id} not found.")
        try:
            row.status         = status.value
            row.actual_outcome = actual_outcome
            row.resolved_at    = datetime.now(tz=timezone.utc)
            if actual_outcome and actual_outcome.get("human_decision"):
                row.override_flag = True
            await self._db.commit()
        except Exception as e:
            await self._db.rollback()
            raise PersistenceError(f"update_resolution failed: {e}") from e

    async def get_simulation_drift_metrics(self, lookback_days: int) -> dict:
        from sqlalchemy import func, case
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=lookback_days)
        result = await self._db.execute(
            select(
                func.count().label("n_total"),
                func.count().filter(
                    DecisionSimulationORM.status == "RESOLVED"
                ).label("n_resolved"),
                func.count().filter(
                    DecisionSimulationORM.override_flag.is_(True)
                ).label("n_overrides"),
            ).where(DecisionSimulationORM.created_at >= cutoff)
        )
        row = result.one()
        n_total    = row.n_total    or 0
        n_resolved = row.n_resolved or 0
        n_overrides= row.n_overrides or 0
        return {
            "n_simulations":  n_total,
            "n_resolved":     n_resolved,
            "override_rate":  n_overrides / max(n_total, 1),
            "approval_success_rate": None,   # requires joining with actuals
            "roi_prediction_bias":   None,   # computed by feedback service
        }

    # ------------------------------------------------------------------
    def _orm_to_entity(self, row: DecisionSimulationORM) -> RecommendationObject:
        return RecommendationObject(
            simulation_id=row.simulation_id,
            store_id=row.store_id,
            item_id=row.item_id,
            recommendation=DecisionState(row.recommendation),
            decision_score=row.decision_score,
            expected_roi=row.predicted_roi or 0.0,
            probability_profitable=row.probability_profitable or 0.5,
            uncertainty_band=row.uncertainty_band or {},
            baseline_forecast=0.0,
            promo_forecast=0.0,
            expected_uplift_units=0.0,
            expected_uplift_pct=row.predicted_uplift_pct or 0.0,
            revenue_uplift_pct=0.0,
            revenue_roi_pct=0.0,
            net_roi_pct=row.predicted_roi or 0.0,
            cannibalization_penalty=0.0,
            risk_notes=row.risk_notes or [],
            recommended_action=row.recommended_action,
            config_snapshot=row.config_snapshot or {},
            created_at=row.created_at,
            resolved_at=row.resolved_at,
            actual_outcome=row.actual_outcome,
        )
