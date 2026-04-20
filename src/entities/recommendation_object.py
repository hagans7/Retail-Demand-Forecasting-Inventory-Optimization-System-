"""Recommendation object — final output of the V2 Decision Intelligence pipeline.

Produced by SimulatePromoROIService (orchestrator).
Persisted to decision_simulations table.
Consumed by /simulate-promo/roi endpoint and FeedbackRecalibrationPipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class DecisionState(str, Enum):
    APPROVE = "APPROVE"
    REVIEW  = "REVIEW"
    REJECT  = "REJECT"


@dataclass
class RecommendationObject:
    """Final output of V2 pipeline. Immutable after creation.

    config_snapshot is captured at creation time and frozen. This enables
    reproducibility: any historical decision can be re-explained with the exact
    parameter set (decision weights, approval thresholds) active at that time.

    override_allowed is always True. System is decision support, not autonomous.
    Human overrides are logged via actual_outcome.human_decision for V3 signal.

    risk_notes: max 3 items, ordered by severity, plain English.
    """
    simulation_id          : str
    store_id               : str
    item_id                : str
    recommendation         : DecisionState
    decision_score         : float      # 0.0–1.0 weighted composite
    expected_roi           : float      # net ROI at q60, after cannibalization (%)
    probability_profitable : float      # 0.0–1.0 fraction of MC scenarios
    uncertainty_band       : dict       # {"p10": float, "p50": float, "p90": float}
    baseline_forecast      : float      # total units without promo (7d)
    promo_forecast         : float      # total units with promo q60 (7d)
    expected_uplift_units  : float
    expected_uplift_pct    : float
    revenue_uplift_pct     : float
    revenue_roi_pct        : float      # before COGS deduction
    net_roi_pct            : float      # after COGS and execution cost
    cannibalization_penalty: float      # % net basket revenue lost
    impacted_items         : list[dict] = field(default_factory=list)
    additional_stock_needed: int = 0
    stock_feasible         : bool = True
    risk_notes             : list[str] = field(default_factory=list)
    recommended_action     : str | None = None
    override_allowed       : bool = True
    config_snapshot        : dict = field(default_factory=dict)   # frozen at creation
    cogs_source            : str = "scenario_default"
    model_version          : str = ""
    cold_start_tier        : str = "NONE"
    created_at             : datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    resolved_at            : datetime | None = None
    actual_outcome         : dict | None = None   # filled by feedback pipeline

    def __post_init__(self) -> None:
        if not (0.0 <= self.decision_score <= 1.0):
            raise ValueError(f"decision_score must be 0.0–1.0, got {self.decision_score}")
        if len(self.risk_notes) > 3:
            raise ValueError("risk_notes must have at most 3 items")

    def is_approved(self) -> bool:
        return self.recommendation == DecisionState.APPROVE

    def requires_human_review(self) -> bool:
        return self.recommendation == DecisionState.REVIEW

    def was_overridden(self) -> bool:
        if self.actual_outcome is None:
            return False
        return self.actual_outcome.get("human_decision") is not None
