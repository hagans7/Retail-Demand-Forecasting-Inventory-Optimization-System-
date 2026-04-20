"""Tests — ComputeDecisionScoreService."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.core.exceptions.app_exceptions import ConfigSafetyBoundsViolationError
from src.entities.recommendation_object import DecisionState
from src.services.compute_decision_score import ComputeDecisionScoreService


def _make_service(weights=None, approve=0.70, review=0.40):
    config_repo = MagicMock()

    async def get_config(key):
        if key == "DECISION_WEIGHTS":
            cfg = MagicMock()
            cfg.config_value = weights or {"roi":0.40,"stock":0.25,"uncertainty":0.20,"substitution":0.15}
            return cfg
        if key == "DECISION_APPROVE_THRESHOLD":
            cfg = MagicMock(); cfg.config_value = approve; return cfg
        if key == "DECISION_REVIEW_THRESHOLD":
            cfg = MagicMock(); cfg.config_value = review; return cfg
        return None

    config_repo.get_config = get_config
    return ComputeDecisionScoreService(config_repo)


@pytest.mark.asyncio
async def test_approve_when_all_components_high():
    svc = _make_service()
    result = await svc.execute(
        net_roi_pct=25.0, stock_feasibility_score=0.95,
        probability_profitable=0.90, cannibalization_penalty_pct=1.0,
    )
    assert result.decision_state == DecisionState.APPROVE
    assert result.total_score >= 0.70


@pytest.mark.asyncio
async def test_reject_when_roi_negative_and_uncertainty_low():
    svc = _make_service()
    result = await svc.execute(
        net_roi_pct=-30.0, stock_feasibility_score=0.20,
        probability_profitable=0.10, cannibalization_penalty_pct=15.0,
    )
    assert result.decision_state == DecisionState.REJECT
    assert result.total_score < 0.40


@pytest.mark.asyncio
async def test_review_when_borderline():
    svc = _make_service()
    result = await svc.execute(
        net_roi_pct=2.0, stock_feasibility_score=0.6,
        probability_profitable=0.55, cannibalization_penalty_pct=5.0,
    )
    assert result.decision_state in (DecisionState.REVIEW, DecisionState.APPROVE)


@pytest.mark.asyncio
async def test_uses_default_weights_when_config_unavailable():
    config_repo = MagicMock()
    config_repo.get_config = AsyncMock(side_effect=Exception("Redis down"))
    svc = ComputeDecisionScoreService(config_repo)
    result = await svc.execute(
        net_roi_pct=10.0, stock_feasibility_score=0.8,
        probability_profitable=0.75, cannibalization_penalty_pct=2.0,
    )
    from src.core.constants.decision_constants import DEFAULT_DECISION_WEIGHTS
    assert result.weights_used == DEFAULT_DECISION_WEIGHTS


@pytest.mark.asyncio
async def test_raises_when_weights_do_not_sum_to_one():
    bad_weights = {"roi": 0.50, "stock": 0.50, "uncertainty": 0.30, "substitution": 0.10}
    svc = _make_service(weights=bad_weights)
    with pytest.raises(ConfigSafetyBoundsViolationError):
        await svc.execute(10.0, 0.8, 0.75, 2.0)


@pytest.mark.asyncio
async def test_primary_risk_driver_is_lowest_component():
    svc = _make_service()
    # Make stock very low
    result = await svc.execute(
        net_roi_pct=15.0, stock_feasibility_score=0.05,
        probability_profitable=0.85, cannibalization_penalty_pct=1.0,
    )
    assert result.primary_risk_driver == "stock"
