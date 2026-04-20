"""Analytics snapshot entity."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class WeeklyAnalyticsSnapshot:
    """Aggregate business analytics for one reporting period.

    Produced by GenerateAnalyticsSnapshotService (weekly Monday 07:00).
    Stored in analytics_snapshots table; served via /analytics/summary.
    """
    snapshot_id     : str
    period_start    : date
    period_end      : date
    computed_at     : datetime
    metrics         : dict = field(default_factory=dict)
    revenue_metrics : dict = field(default_factory=dict)
    promo_effectiveness: dict = field(default_factory=dict)
