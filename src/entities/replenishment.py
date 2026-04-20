"""Replenishment entities — operational inventory signal."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class StockoutRisk(str, Enum):
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class ReplenishmentSignal:
    """Actionable inventory signal produced by ComputeReplenishmentService.

    Consumed by /replenishment/ API endpoint and by SimulatePromoROIService
    (stock_feasibility_score component of decision scoring).
    """
    store_id               : str
    item_id                : str
    forecast_7d            : float
    current_stock          : int
    safety_factor          : float
    recommended_restock_qty: int
    stockout_risk          : StockoutRisk
    stock_feasibility_score: float = 1.0   # 0.0–1.0; used by V2 decision scoring
    reason_codes           : list[str] = field(default_factory=list)
    revenue_at_risk        : float | None = None
    cold_start_tier        : str = "NONE"

    def __post_init__(self) -> None:
        if not (0.0 <= self.stock_feasibility_score <= 1.0):
            raise ValueError(
                f"stock_feasibility_score must be 0.0–1.0, got {self.stock_feasibility_score}"
            )
        if self.recommended_restock_qty < 0:
            raise ValueError("recommended_restock_qty cannot be negative")

    def days_of_stock_remaining(self) -> float:
        """Days of current stock before stockout at forecast demand rate."""
        daily_avg = self.forecast_7d / 7
        if daily_avg <= 0:
            return float("inf")
        return self.current_stock / daily_avg

    def is_urgent(self) -> bool:
        """True when immediate action is required."""
        return self.stockout_risk in (StockoutRisk.HIGH, StockoutRisk.CRITICAL)

    def coverage_gap(self) -> float:
        """Days short of 7-day coverage (positive = insufficient stock)."""
        return max(0.0, 7.0 - self.days_of_stock_remaining())
