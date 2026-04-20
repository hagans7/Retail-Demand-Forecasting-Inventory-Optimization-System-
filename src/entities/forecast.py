"""
Forecast entities — core output of the predictive engine.

Produced by GenerateForecastService and HandleColdStartService.
Consumed by ComputeReplenishmentService, SimulatePromoUpliftService,
SimulatePromoROIService, ExplainForecastService.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class ColdStartTier(str, Enum):
    """Signals confidence level of forecast to downstream consumers."""
    NONE         = "NONE"           # full history — standard model
    TIER1_PROXY  = "TIER1_PROXY"    # 0–6 days history — cross-store average
    TIER2_REDUCED= "TIER2_REDUCED"  # 7–27 days — lag_7 only inference


@dataclass
class DailyForecast:
    """Single-day forecast value object.

    feature_snapshot stores top-5 gain-importance feature values at inference
    time. Used for post-hoc debugging without re-running feature engineering.
    """
    date             : date
    predicted_sales  : float
    lower_bound      : float          # q40 prediction
    upper_bound      : float          # q80 prediction
    revenue_estimate : float | None = None  # predicted_sales × price
    feature_snapshot : dict  | None = None  # top-5 features at inference

    def __post_init__(self) -> None:
        if self.predicted_sales < 0:
            raise ValueError(
                f"predicted_sales must be >= 0, got {self.predicted_sales}"
            )


@dataclass
class ForecastResult:
    """Aggregate forecast for a single store-item pair.

    The cold_start_tier field signals downstream consumers to apply appropriate
    confidence degradation and safety factor uplift:
        TIER1_PROXY   → error ~1.13x vs full model → SAFETY_FACTOR_COLD_START
        TIER2_REDUCED → error ~1.01x vs full model → SAFETY_FACTOR_COLD_START
        NONE          → standard safety factors apply

    Invariant: len(daily_forecasts) == horizon_days.
    """
    store_id        : str
    item_id         : str
    horizon_days    : int
    daily_forecasts : list[DailyForecast] = field(default_factory=list)
    model_version   : str = ""
    cold_start_tier : ColdStartTier = ColdStartTier.NONE
    generated_at    : str = ""

    def __post_init__(self) -> None:
        if self.daily_forecasts and len(self.daily_forecasts) != self.horizon_days:
            raise ValueError(
                f"len(daily_forecasts) must equal horizon_days ({self.horizon_days}), "
                f"got {len(self.daily_forecasts)}"
            )

    def total_7d_demand(self) -> float:
        """Sum of predicted_sales across all forecast days."""
        return sum(d.predicted_sales for d in self.daily_forecasts)

    def total_7d_revenue(self) -> float | None:
        """Sum of revenue_estimate if available for all days."""
        if any(d.revenue_estimate is None for d in self.daily_forecasts):
            return None
        return sum(d.revenue_estimate for d in self.daily_forecasts)  # type: ignore[misc]

    def peak_day(self) -> DailyForecast:
        """Day with highest predicted_sales."""
        if not self.daily_forecasts:
            raise ValueError("No daily forecasts available.")
        return max(self.daily_forecasts, key=lambda d: d.predicted_sales)

    def has_promo_day(self, promo_dates: list[date]) -> bool:
        """True if any forecast day falls in promo_dates."""
        forecast_dates = {d.date for d in self.daily_forecasts}
        return bool(forecast_dates & set(promo_dates))

    def is_cold_start(self) -> bool:
        """True when cold_start_tier is not NONE."""
        return self.cold_start_tier != ColdStartTier.NONE

    def confidence_label(self) -> str:
        """Human-readable confidence level for API consumers."""
        if self.cold_start_tier == ColdStartTier.TIER1_PROXY:
            return "LOW"
        if self.cold_start_tier == ColdStartTier.TIER2_REDUCED:
            return "MEDIUM"
        return "HIGH"
