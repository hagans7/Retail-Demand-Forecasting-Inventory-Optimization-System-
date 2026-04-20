"""Abstract base for elasticity and financial assumptions repository — V2."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseElasticityRepository(ABC):
    """Contract for item_elasticity_observed and item_financial_assumptions tables.

    Category 4 parameters: auto-updated by feedback pipeline, human-overridable.
    """

    @abstractmethod
    async def get_elasticity(
        self,
        item_id: str,
        store_id: str,
    ) -> float | None:
        """Return observed elasticity coefficient. None if no data yet.

        Caller falls back to analytics_constants.BASELINE_PRICE_SALES_CORR.
        """

    @abstractmethod
    async def update_elasticity_ema(
        self,
        item_id: str,
        store_id: str,
        new_estimate: float,
        source: str,
    ) -> None:
        """Apply EMA update to elasticity_observed.

        EMA formula implemented as atomic SQL ON CONFLICT DO UPDATE to avoid
        read-modify-write race conditions under concurrent writes.

        Args:
            source: "feedback_loop" | "human_override"

        Raises:
            PersistenceError: On DB write failure.
        """

    @abstractmethod
    async def get_financial_assumptions(self, item_id: str) -> dict:
        """Return COGS structure for item. Always returns a row.

        Priority: item_specific row → __default__ row (sentinel always exists).
        Never raises on missing item_id — falls through to __default__.

        Returns:
            {cogs_pct, promo_fixed_cost, holding_cost_per_day, source}
            source: "item_specific" | "scenario_default"
        """

    @abstractmethod
    async def upsert_financial_assumptions(
        self,
        item_id: str,
        cogs_pct: float,
        promo_fixed_cost: float,
        holding_cost_per_day: float,
        updated_by: str,
    ) -> None:
        """Insert or update COGS structure for item.

        Raises:
            PersistenceError: On DB write failure.
        """
