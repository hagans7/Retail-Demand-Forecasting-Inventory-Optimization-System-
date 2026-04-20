"""Generate analytics snapshot service — weekly aggregate."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from src.core.logging.logger import get_logger
from src.entities.analytics_snapshot import WeeklyAnalyticsSnapshot
from src.interfaces.base_analytics_repository import BaseAnalyticsRepository


class GenerateAnalyticsSnapshotService:
    """Aggregates weekly business analytics into a snapshot for /analytics/summary."""

    def __init__(self, analytics_repo: BaseAnalyticsRepository) -> None:
        self._analytics = analytics_repo
        self._logger    = get_logger(__name__)

    async def execute(self, run_date: date | None = None) -> WeeklyAnalyticsSnapshot:
        today  = run_date or date.today()
        start  = today - timedelta(days=7)

        # Revenue metrics
        revenue_df = await self._analytics.get_revenue_for_period(start, today)
        if not revenue_df.empty and "promo" in revenue_df.columns:
            avg_rev_promo  = float(revenue_df[revenue_df["promo"]==1]["revenue"].mean()) if len(revenue_df[revenue_df["promo"]==1]) > 0 else 0.0
            avg_rev_normal = float(revenue_df[revenue_df["promo"]==0]["revenue"].mean()) if len(revenue_df[revenue_df["promo"]==0]) > 0 else 0.0
            rev_uplift     = (avg_rev_promo - avg_rev_normal) / max(avg_rev_normal, 0.01) * 100
        else:
            avg_rev_promo = avg_rev_normal = rev_uplift = 0.0

        # Promo effectiveness
        promo_eff = await self._analytics.get_item_promo_sensitivity()

        snapshot = WeeklyAnalyticsSnapshot(
            snapshot_id=str(uuid.uuid4()),
            period_start=start, period_end=today,
            computed_at=datetime.now(tz=timezone.utc),
            metrics={"n_rows_analyzed": len(revenue_df)},
            revenue_metrics={
                "avg_revenue_promo":  round(avg_rev_promo,  4),
                "avg_revenue_normal": round(avg_rev_normal, 4),
                "revenue_uplift_pct": round(rev_uplift, 2),
            },
            promo_effectiveness={"top_items": promo_eff[:10]},
        )
        await self._analytics.save_analytics_snapshot(snapshot)
        self._logger.info("Analytics snapshot generated",
                          extra={"snapshot_id": snapshot.snapshot_id,
                                 "operation": "generate_analytics_snapshot"})
        return snapshot
