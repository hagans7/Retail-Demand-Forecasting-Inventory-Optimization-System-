"""Tests for V2 entity invariants — RecommendationObject."""
from __future__ import annotations

import pytest
from src.entities.recommendation_object import DecisionState, RecommendationObject


def _make_rec(**kwargs) -> RecommendationObject:
    defaults = dict(
        simulation_id="sim-001", store_id="store_1", item_id="item_1",
        recommendation=DecisionState.APPROVE,
        decision_score=0.75, expected_roi=10.2, probability_profitable=0.84,
        uncertainty_band={"p10": 3.0, "p50": 10.2, "p90": 14.5},
        baseline_forecast=76.4, promo_forecast=113.2,
        expected_uplift_units=36.8, expected_uplift_pct=48.2,
        revenue_uplift_pct=18.5, revenue_roi_pct=18.5, net_roi_pct=10.2,
        cannibalization_penalty=2.1, risk_notes=[],
    )
    defaults.update(kwargs)
    return RecommendationObject(**defaults)


def test_is_approved_true():
    obj = _make_rec(recommendation=DecisionState.APPROVE)
    assert obj.is_approved() is True


def test_is_approved_false_when_review():
    obj = _make_rec(recommendation=DecisionState.REVIEW, decision_score=0.55)
    assert obj.is_approved() is False


def test_requires_review_true():
    obj = _make_rec(recommendation=DecisionState.REVIEW, decision_score=0.55)
    assert obj.requires_human_review() is True


def test_decision_score_must_be_0_to_1():
    with pytest.raises(ValueError):
        _make_rec(decision_score=1.5)

    with pytest.raises(ValueError):
        _make_rec(decision_score=-0.1)


def test_risk_notes_max_3_items():
    with pytest.raises(ValueError):
        _make_rec(risk_notes=["a", "b", "c", "d"])


def test_risk_notes_exactly_3_is_valid():
    obj = _make_rec(risk_notes=["a", "b", "c"])
    assert len(obj.risk_notes) == 3


def test_was_overridden_false_before_resolution():
    obj = _make_rec()
    assert obj.was_overridden() is False


def test_was_overridden_true_after_human_decision():
    obj = _make_rec()
    obj.actual_outcome = {"human_decision": "REJECT", "reason": "competitor promo"}
    assert obj.was_overridden() is True


def test_override_allowed_always_true():
    obj = _make_rec()
    assert obj.override_allowed is True
