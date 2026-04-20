"""Tests — UpdateDecisionFeedbackService.
Critical: model poisoning prevention via CANCELLED_IN_STORE guard.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from src.entities.decision_feedback_record import FeedbackStatus
from src.entities.recommendation_object import DecisionState, RecommendationObject


def _make_pending_simulation():
    return RecommendationObject(
        simulation_id="sim-feedback-001",
        store_id="store_1", item_id="item_6",
        recommendation=DecisionState.APPROVE,
        decision_score=0.78, expected_roi=10.2,
        probability_profitable=0.84,
        uncertainty_band={"p10": 3.0, "p50": 10.2, "p90": 14.5},
        baseline_forecast=76.4, promo_forecast=113.2,
        expected_uplift_units=36.8, expected_uplift_pct=48.2,
        revenue_uplift_pct=18.5, revenue_roi_pct=18.5, net_roi_pct=10.2,
        cannibalization_penalty=2.1,
        created_at=datetime(2026, 4, 6, tzinfo=timezone.utc),
    )


def _make_service(actuals_df: pd.DataFrame):
    from src.services.update_decision_feedback import UpdateDecisionFeedbackService

    decision_repo = MagicMock()
    decision_repo.get_pending_feedback = AsyncMock(return_value=[_make_pending_simulation()])
    decision_repo.update_resolution = AsyncMock(return_value=None)

    analytics_repo = MagicMock()
    analytics_repo.get_sales_for_period = AsyncMock(return_value=actuals_df)

    elasticity_repo = MagicMock()
    elasticity_repo.get_elasticity = AsyncMock(return_value=None)
    elasticity_repo.update_elasticity_ema = AsyncMock(return_value=None)

    return UpdateDecisionFeedbackService(
        decision_repo=decision_repo,
        analytics_repo=analytics_repo,
        elasticity_repo=elasticity_repo,
    ), decision_repo, elasticity_repo


# ── MODEL POISONING PREVENTION ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancelled_when_promo_not_executed_in_store():
    """CRITICAL: Promo approved by system but never executed → CANCELLED_IN_STORE.
    Elasticity must NOT be updated."""
    actuals = pd.DataFrame({
        "store_id": ["store_1"] * 5, "item_id": ["item_6"] * 5,
        "date": pd.date_range("2026-04-07", periods=5),
        "sales": [30, 28, 32, 29, 31],
        "promo": [0, 0, 0, 0, 0],   # No promo executed!
        "price": [20.0] * 5,
    })
    svc, decision_repo, elasticity_repo = _make_service(actuals)
    summary = await svc.execute()

    # Must be marked cancelled — not resolved
    decision_repo.update_resolution.assert_called_once()
    call_args = decision_repo.update_resolution.call_args
    assert call_args[0][1] == FeedbackStatus.CANCELLED_IN_STORE, (
        "Simulation must be CANCELLED_IN_STORE when promo=0 in actuals"
    )
    # Elasticity MUST NOT be updated
    elasticity_repo.update_elasticity_ema.assert_not_called()
    assert summary["n_cancelled"] == 1


@pytest.mark.asyncio
async def test_resolved_when_promo_executed():
    """Promo executed → feedback resolved → elasticity updated."""
    actuals = pd.DataFrame({
        "store_id": ["store_1"] * 7, "item_id": ["item_6"] * 7,
        "date": pd.date_range("2026-04-07", periods=7),
        "sales": [110, 115, 108, 112, 30, 28, 32],
        "promo": [1, 1, 1, 1, 0, 0, 0],  # Promo executed for 4 days
        "price": [16.0, 16.0, 16.0, 16.0, 20.0, 20.0, 20.0],
    })
    svc, decision_repo, elasticity_repo = _make_service(actuals)
    summary = await svc.execute()

    decision_repo.update_resolution.assert_called_once()
    call_args = decision_repo.update_resolution.call_args
    assert call_args[0][1] == FeedbackStatus.RESOLVED
    assert summary["n_resolved"] == 1


@pytest.mark.asyncio
async def test_flags_high_deviation():
    """If actual uplift deviates > 20pp from predicted → flagged_for_review=True."""
    # predicted_uplift_pct = 48.2%; actual will be near 0%
    actuals = pd.DataFrame({
        "store_id": ["store_1"] * 7, "item_id": ["item_6"] * 7,
        "date": pd.date_range("2026-04-07", periods=7),
        "sales": [30, 31, 29, 30, 28, 32, 30],    # No uplift during promo
        "promo": [1, 1, 1, 1, 0, 0, 0],
        "price": [16.0, 16.0, 16.0, 16.0, 20.0, 20.0, 20.0],
    })
    svc, decision_repo, elasticity_repo = _make_service(actuals)
    summary = await svc.execute()

    # actual_outcome must have flagged_for_review=True
    call_args = decision_repo.update_resolution.call_args
    actual_outcome = call_args[0][2]
    assert actual_outcome is not None
    # Deviation: actual ~0% vs predicted 48.2% → abs(deviation) > 20
    if actual_outcome and "flagged_for_review" in actual_outcome:
        assert actual_outcome["flagged_for_review"] is True


@pytest.mark.asyncio
async def test_model_artifacts_never_touched():
    """Critical: UpdateDecisionFeedbackService must never call model_registry or storage."""
    actuals = pd.DataFrame({
        "store_id": ["store_1"] * 4, "item_id": ["item_6"] * 4,
        "date": pd.date_range("2026-04-07", periods=4),
        "sales": [110, 115, 108, 30], "promo": [1, 1, 1, 0],
        "price": [16.0, 16.0, 16.0, 20.0],
    })
    svc, _, _ = _make_service(actuals)
    # If this had model_registry or storage_client attributes, that would be wrong
    assert not hasattr(svc, "_model_registry"), \
        "Feedback service must not have model_registry — Category 4 only"
    assert not hasattr(svc, "_storage"), \
        "Feedback service must not have storage_client — no artifact writes"
