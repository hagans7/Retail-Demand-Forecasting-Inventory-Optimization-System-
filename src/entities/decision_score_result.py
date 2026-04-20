"""Decision score result entity."""
from __future__ import annotations

from dataclasses import dataclass, field

from src.entities.recommendation_object import DecisionState


@dataclass
class DecisionScoreResult:
    """Weighted composite score mapping to APPROVE/REVIEW/REJECT.

    weights_used captures the exact weights applied at scoring time.
    Included in RecommendationObject.config_snapshot for auditability.
    """
    total_score           : float   # 0.0–1.0
    roi_component         : float   # normalized ROI score
    stock_component       : float   # stock feasibility score
    uncertainty_component : float   # probability_profitable
    substitution_component: float   # 1.0 - cannibalization_risk
    weights_used          : dict    # snapshot of DECISION_WEIGHTS at computation
    decision_state        : DecisionState
    primary_risk_driver   : str     # component with lowest weighted score

    def __post_init__(self) -> None:
        if not (0.0 <= self.total_score <= 1.0):
            raise ValueError(f"total_score must be 0.0-1.0, got {self.total_score}")

    def explain(self) -> str:
        return (
            f"Score={self.total_score:.2f} → {self.decision_state.value}. "
            f"Components: roi={self.roi_component:.2f}, "
            f"stock={self.stock_component:.2f}, "
            f"uncertainty={self.uncertainty_component:.2f}, "
            f"substitution={self.substitution_component:.2f}. "
            f"Primary risk: {self.primary_risk_driver}."
        )

    def is_borderline(self, approve_threshold: float, review_threshold: float) -> bool:
        return (
            abs(self.total_score - approve_threshold) <= 0.05
            or abs(self.total_score - review_threshold) <= 0.05
        )
