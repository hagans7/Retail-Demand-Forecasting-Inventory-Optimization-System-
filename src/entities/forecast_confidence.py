"""Forecast confidence entity — three-quantile prediction bands."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class DailyConfidenceBand:
    date        : date
    lower_bound : float   # q40
    central     : float   # q60 — same as main forecast
    upper_bound : float   # q80
    uncertainty_width: float  # (q80 - q40) / q60
    uncertainty_label: str   # "NARROW" | "MODERATE" | "WIDE"


@dataclass
class ForecastConfidence:
    """Three-quantile forecast for a store-item pair.

    Requires three model artifacts per version_tag (q40, q60, q80).
    Training pipeline registers all three; only q60 is is_production=True.
    """
    store_id        : str
    item_id         : str
    version_tag     : str
    daily_bands     : list[DailyConfidenceBand] = field(default_factory=list)
