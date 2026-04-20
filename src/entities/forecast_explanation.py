"""Forecast explanation entities — SHAP-based driver translation."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FeatureDriver:
    """Single feature contribution to a forecast value.

    label is from FEATURE_BUSINESS_LABELS — never feature_name raw.
    """
    label        : str
    feature_name : str
    impact       : float    # SHAP value (signed)
    direction    : str      # "positive" | "negative"


@dataclass
class ForecastExplanation:
    """SHAP-based forecast explanation in business language.

    Produced by ExplainForecastService.
    label translations from FEATURE_BUSINESS_LABELS (feature_constants.py).
    """
    store_id     : str
    item_id      : str
    target_date  : object   # date
    base_value   : float    # model expected output (training mean)
    drivers      : list[FeatureDriver] = field(default_factory=list)
    final_forecast: float = 0.0

    def top_positive_drivers(self, n: int = 3) -> list[FeatureDriver]:
        pos = [d for d in self.drivers if d.direction == "positive"]
        return sorted(pos, key=lambda d: d.impact, reverse=True)[:n]

    def top_negative_drivers(self, n: int = 2) -> list[FeatureDriver]:
        neg = [d for d in self.drivers if d.direction == "negative"]
        return sorted(neg, key=lambda d: d.impact)[:n]

    def promo_contribution(self) -> float:
        promo_features = {"promo", "promo_streak_day", "days_since_last_promo"}
        return sum(d.impact for d in self.drivers if d.feature_name in promo_features)

    def temporal_contribution(self) -> float:
        temporal_prefix = ("lag_", "rolling_")
        return sum(
            d.impact for d in self.drivers
            if any(d.feature_name.startswith(p) for p in temporal_prefix)
        )
