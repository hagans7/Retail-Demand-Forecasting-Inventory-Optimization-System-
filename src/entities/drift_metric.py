"""Drift metric entity."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class DriftSeverity(str, Enum):
    NONE     = "NONE"
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class FeatureDriftMetric:
    """PSI-based feature drift metric.

    psi_score is None for target distribution monitoring (uses shift_pct instead).

    PSI thresholds: <0.1=NONE, 0.1-0.2=LOW/MEDIUM, >0.2=HIGH/CRITICAL.
    """
    feature_name   : str
    current_mean   : float
    training_mean  : float
    current_std    : float
    training_std   : float
    severity       : DriftSeverity
    computed_at    : datetime
    psi_score      : float | None = None   # None for target drift
    shift_pct      : float | None = None   # None for feature drift

    def is_drifted(self) -> bool:
        if self.psi_score is not None:
            return self.psi_score > 0.20
        return abs(self.shift_pct or 0) > 15.0

    def relative_mean_shift(self) -> float:
        if self.training_mean == 0:
            return 0.0
        return (self.current_mean - self.training_mean) / self.training_mean
