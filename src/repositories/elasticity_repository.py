"""Elasticity repository — item_elasticity_observed and item_financial_assumptions.

Category 4: auto-updated by feedback pipeline via atomic SQL EMA.
EMA update uses ON CONFLICT DO UPDATE in SQL to prevent read-modify-write races.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.constants.decision_constants import ELASTICITY_ROLLING_ALPHA
from src.core.exceptions.app_exceptions import PersistenceError
from src.core.logging.logger import get_logger
from src.db_models.decision_orm import ItemElasticityObservedORM, ItemFinancialAssumptionORM
from src.interfaces.base_elasticity_repository import BaseElasticityRepository


class ElasticityRepository(BaseElasticityRepository):
    """Manages observed elasticity coefficients and COGS assumptions."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session
        self._logger = get_logger(__name__)

    async def get_elasticity(self, item_id: str, store_id: str) -> float | None:
        """O(1) lookup via PRIMARY KEY (item_id, store_id)."""
        row = await self._db.get(ItemElasticityObservedORM, (item_id, store_id))
        return row.elasticity_observed if row else None

    async def update_elasticity_ema(
        self,
        item_id: str,
        store_id: str,
        new_estimate: float,
        source: str,
    ) -> None:
        """Atomic EMA update via SQL upsert.

        EMA formula in SQL prevents concurrent-write race conditions.
        new = alpha × new_estimate + (1-alpha) × existing
        alpha = ELASTICITY_ROLLING_ALPHA (0.3)
        """
        alpha = ELASTICITY_ROLLING_ALPHA
        try:
            await self._db.execute(
                text("""
                    INSERT INTO item_elasticity_observed
                        (item_id, store_id, elasticity_initial, elasticity_observed,
                         n_observations, last_calibrated_at, source)
                    VALUES
                        (:item_id, :store_id, :new_est, :new_est, 1, NOW(), :source)
                    ON CONFLICT (item_id, store_id) DO UPDATE SET
                        elasticity_observed = :alpha * :new_est
                                           + (1.0 - :alpha) * item_elasticity_observed.elasticity_observed,
                        n_observations      = item_elasticity_observed.n_observations + 1,
                        last_calibrated_at  = NOW(),
                        source              = :source
                """),
                {
                    "item_id": item_id,
                    "store_id": store_id,
                    "new_est": new_estimate,
                    "alpha": alpha,
                    "source": source,
                },
            )
            await self._db.commit()
            self._logger.info(
                "Elasticity EMA updated",
                extra={
                    "item_id": item_id, "store_id": store_id,
                    "new_estimate": new_estimate, "source": source,
                    "operation": "update_elasticity_ema",
                },
            )
        except Exception as e:
            await self._db.rollback()
            raise PersistenceError(f"update_elasticity_ema failed: {e}") from e

    async def get_financial_assumptions(self, item_id: str) -> dict:
        """Always returns a row. Falls back to __default__ sentinel.

        Priority: item-specific row → __default__ row.
        The __default__ row is guaranteed by migration 001 seed data.
        """
        row = await self._db.get(ItemFinancialAssumptionORM, item_id)
        if row is None:
            row = await self._db.get(ItemFinancialAssumptionORM, "__default__")
            source = "scenario_default"
        else:
            source = "item_specific"

        if row is None:
            # Should never happen — __default__ always exists after migration
            self._logger.warning(
                "__default__ COGS row missing — using hardcoded fallback",
                extra={"item_id": item_id, "operation": "get_financial_assumptions"},
            )
            return {
                "cogs_pct": 0.60,
                "promo_fixed_cost": 100.0,
                "holding_cost_per_day": 0.015,
                "source": "hardcoded_emergency_fallback",
            }

        return {
            "cogs_pct":              row.cogs_pct,
            "promo_fixed_cost":      row.promo_fixed_cost,
            "holding_cost_per_day":  row.holding_cost_per_day,
            "source":                source,
        }

    async def upsert_financial_assumptions(
        self,
        item_id: str,
        cogs_pct: float,
        promo_fixed_cost: float,
        holding_cost_per_day: float,
        updated_by: str,
    ) -> None:
        try:
            existing = await self._db.get(ItemFinancialAssumptionORM, item_id)
            if existing:
                existing.cogs_pct = cogs_pct
                existing.promo_fixed_cost = promo_fixed_cost
                existing.holding_cost_per_day = holding_cost_per_day
                existing.updated_by = updated_by
            else:
                self._db.add(ItemFinancialAssumptionORM(
                    item_id=item_id,
                    cogs_pct=cogs_pct,
                    promo_fixed_cost=promo_fixed_cost,
                    holding_cost_per_day=holding_cost_per_day,
                    updated_by=updated_by,
                ))
            await self._db.commit()
        except Exception as e:
            await self._db.rollback()
            raise PersistenceError(f"upsert_financial_assumptions failed: {e}") from e
