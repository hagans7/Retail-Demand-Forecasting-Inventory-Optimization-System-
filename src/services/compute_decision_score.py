"""Compute decision score — weighted composite → APPROVE / REVIEW / REJECT.

Algorithm:
    1. Normalize each component to 0.0-1.0
    2. Load DECISION_WEIGHTS from business_configs (Category 3, Redis-cached)
    3. Weighted sum
    4. Classify via DECISION_APPROVE_THRESHOLD / DECISION_REVIEW_THRESHOLD
    5. Identify primary_risk_driver (lowest weighted component)

ROI normalization via sigmoid centred at 0% ROI:
    roi_score = 1 / (1 + exp(-roi_pct / 20.0))
    ROI=0%  → 0.50  (neutral)
    ROI=20% → ~0.73 (good)
    ROI=-20%→ ~0.27 (bad)
"""
from __future__ import annotations

import math

from src.core.constants.business_constants import SAFETY_BOUNDS
from src.core.constants.decision_constants import (
    DEFAULT_DECISION_APPROVE_THRESHOLD,
    DEFAULT_DECISION_REVIEW_THRESHOLD,
    DEFAULT_DECISION_WEIGHTS,
)
from src.core.exceptions.app_exceptions import (
    CacheError,
    ConfigSafetyBoundsViolationError,
)
from src.core.logging.logger import get_logger
from src.entities.decision_score_result import DecisionScoreResult
from src.entities.recommendation_object import DecisionState
from src.interfaces.base_config_repository import BaseConfigRepository


class ComputeDecisionScoreService:
    """Computes weighted composite score from four independent assessments.

    Weights and thresholds loaded from business_configs (Category 3 — DB-backed,
    Redis-cached, runtime-configurable). Falls back to decision_constants defaults
    if DB unavailable.
    """

    def __init__(self, config_repo: BaseConfigRepository) -> None:
        self._config = config_repo
        self._logger = get_logger(__name__)

    async def execute(
        self,
        net_roi_pct: float,
        stock_feasibility_score: float,
        probability_profitable: float,
        cannibalization_penalty_pct: float,
    ) -> DecisionScoreResult:
        weights, approve_threshold, review_threshold = await self._load_config()

        # Validate weights sum to 1.0
        weight_sum = sum(weights.values())
        if abs(weight_sum - 1.0) > 1e-4:
            raise ConfigSafetyBoundsViolationError(
                f"DECISION_WEIGHTS do not sum to 1.0: {weight_sum:.4f}"
            )

        # Normalize each component to 0.0-1.0
        roi_score          = self._sigmoid(net_roi_pct / 20.0)
        stock_score        = max(0.0, min(1.0, stock_feasibility_score))
        uncertainty_score  = max(0.0, min(1.0, probability_profitable))
        sub_risk           = max(0.0, min(1.0, cannibalization_penalty_pct / 20.0))
        substitution_score = 1.0 - sub_risk

        components = {
            "roi":          roi_score          * weights["roi"],
            "stock":        stock_score        * weights["stock"],
            "uncertainty":  uncertainty_score  * weights["uncertainty"],
            "substitution": substitution_score * weights["substitution"],
        }
        total_score = sum(components.values())

        # Classify state
        if total_score >= approve_threshold:
            state = DecisionState.APPROVE
        elif total_score >= review_threshold:
            state = DecisionState.REVIEW
        else:
            state = DecisionState.REJECT

        # Primary risk driver = component with lowest weighted contribution
        primary_risk = min(components, key=components.get)  # type: ignore[arg-type]

        self._logger.info(
            "Decision score computed",
            extra={
                "total_score": round(total_score, 3),
                "state": state.value,
                "primary_risk": primary_risk,
                "roi_component": round(roi_score, 3),
                "operation": "compute_decision_score",
            },
        )
        return DecisionScoreResult(
            total_score=round(total_score, 4),
            roi_component=round(roi_score, 4),
            stock_component=round(stock_score, 4),
            uncertainty_component=round(uncertainty_score, 4),
            substitution_component=round(substitution_score, 4),
            weights_used=weights,
            decision_state=state,
            primary_risk_driver=primary_risk,
        )

    # ------------------------------------------------------------------

    async def _load_config(self) -> tuple[dict, float, float]:
        """Load weights and thresholds from business_configs with fallback."""
        try:
            weights_cfg      = await self._config.get_config("DECISION_WEIGHTS")
            approve_cfg      = await self._config.get_config("DECISION_APPROVE_THRESHOLD")
            review_cfg       = await self._config.get_config("DECISION_REVIEW_THRESHOLD")
            weights   = weights_cfg.config_value  if weights_cfg  else DEFAULT_DECISION_WEIGHTS
            approve   = approve_cfg.config_value  if approve_cfg  else DEFAULT_DECISION_APPROVE_THRESHOLD
            review    = review_cfg.config_value   if review_cfg   else DEFAULT_DECISION_REVIEW_THRESHOLD
        except Exception:
            self._logger.warning(
                "Config unavailable — using DEFAULT_DECISION_WEIGHTS",
                extra={"operation": "compute_decision_score"},
            )
            weights = DEFAULT_DECISION_WEIGHTS
            approve = DEFAULT_DECISION_APPROVE_THRESHOLD
            review  = DEFAULT_DECISION_REVIEW_THRESHOLD

        if not isinstance(weights, dict):
            weights = DEFAULT_DECISION_WEIGHTS
        if not isinstance(approve, float):
            approve = float(approve)
        if not isinstance(review, float):
            review = float(review)

        return weights, approve, review

    @staticmethod
    def _sigmoid(x: float) -> float:
        return 1.0 / (1.0 + math.exp(-x))
