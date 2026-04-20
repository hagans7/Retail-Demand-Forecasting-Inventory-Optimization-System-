"""Hypothesis monitoring entities."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class HypothesisStatus(str, Enum):
    CONFIRMED        = "CONFIRMED"
    DEGRADED         = "DEGRADED"
    INVERTED         = "INVERTED"
    INSUFFICIENT_DATA= "INSUFFICIENT_DATA"


@dataclass
class HypothesisResult:
    """Result of one automated hypothesis test.

    Produced by RunHypothesisMonitorService (weekly).
    status = INSUFFICIENT_DATA when sample_size < 30 (statistical guard).
    """
    hypothesis_id  : str
    current_value  : float
    baseline_value : float
    deviation_pct  : float   # (current - baseline) / abs(baseline) × 100
    status         : HypothesisStatus
    period_start   : date
    period_end     : date
    sample_size    : int
    alert_triggered: bool

    def __post_init__(self) -> None:
        if self.sample_size < 30 and self.status != HypothesisStatus.INSUFFICIENT_DATA:
            raise ValueError(
                "sample_size < 30 must have status=INSUFFICIENT_DATA"
            )

    def is_significant_drift(self) -> bool:
        return self.alert_triggered

    def business_interpretation(self) -> str:
        """Plain English summary for dashboard display."""
        msg_map = {
            HypothesisStatus.CONFIRMED:         f"{self.hypothesis_id}: normal. Current={self.current_value:.2f}",
            HypothesisStatus.DEGRADED:          f"{self.hypothesis_id}: degrading. Current={self.current_value:.2f} vs baseline={self.baseline_value:.2f}",
            HypothesisStatus.INVERTED:          f"{self.hypothesis_id}: INVERTED — direction reversed.",
            HypothesisStatus.INSUFFICIENT_DATA: f"{self.hypothesis_id}: insufficient data (n={self.sample_size}).",
        }
        return msg_map[self.status]
