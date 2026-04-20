"""Tests — ComputeDecisionUncertaintyService."""
from __future__ import annotations

import pytest
from src.services.compute_decision_uncertainty import ComputeDecisionUncertaintyService


@pytest.fixture
def svc():
    return ComputeDecisionUncertaintyService()


def test_probability_profitable_near_one_when_all_positive(svc):
    result = svc.execute(roi_q40=5.0, roi_q60=10.0, roi_q80=15.0, seed=42)
    assert result.probability_profitable > 0.95


def test_probability_profitable_near_zero_when_all_negative(svc):
    result = svc.execute(roi_q40=-15.0, roi_q60=-10.0, roi_q80=-5.0, seed=42)
    assert result.probability_profitable < 0.05


def test_p50_close_to_q60(svc):
    result = svc.execute(roi_q40=5.0, roi_q60=10.0, roi_q80=15.0, seed=42)
    assert abs(result.p50 - 10.0) < 2.0


def test_p10_less_than_p50_less_than_p90(svc):
    result = svc.execute(roi_q40=0.0, roi_q60=8.0, roi_q80=16.0, seed=42)
    assert result.p10 < result.p50 < result.p90


def test_mc_stable_across_seeds(svc):
    r1 = svc.execute(roi_q40=3.0, roi_q60=10.0, roi_q80=17.0, seed=1)
    r2 = svc.execute(roi_q40=3.0, roi_q60=10.0, roi_q80=17.0, seed=99)
    # Variance in probability_profitable should be small
    assert abs(r1.probability_profitable - r2.probability_profitable) < 0.05


def test_uncertainty_band_has_required_keys(svc):
    result = svc.execute(roi_q40=1.0, roi_q60=5.0, roi_q80=9.0, seed=42)
    assert {"p10", "p50", "p90"} == set(result.uncertainty_band.keys())


def test_n_scenarios_matches_constant(svc):
    from src.core.constants.decision_constants import UNCERTAINTY_N_SCENARIOS
    result = svc.execute(roi_q40=1.0, roi_q60=5.0, roi_q80=9.0, seed=42)
    assert result.n_scenarios == UNCERTAINTY_N_SCENARIOS
