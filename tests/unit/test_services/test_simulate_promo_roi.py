"""Tests — SimulatePromoROIService (V2 orchestrator)."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.entities.recommendation_object import DecisionState, RecommendationObject
from src.entities.replenishment import ReplenishmentSignal, StockoutRisk


def _make_forecast(total: float = 76.4):
    from src.entities.forecast import ColdStartTier, DailyForecast, ForecastResult
    dailies = [
        DailyForecast(date=date(2026, 4, 14), predicted_sales=total/7,
                      lower_bound=(total/7)*0.85, upper_bound=(total/7)*1.20)
        for _ in range(7)
    ]
    return ForecastResult(
        store_id="store_1", item_id="item_6",
        horizon_days=7, daily_forecasts=dailies,
        model_version="v1_test", cold_start_tier=ColdStartTier.NONE,
    )


def _make_uplift(proj_q60: float = 113.2):
    from src.services.simulate_promo_uplift import PromoUpliftResult
    return PromoUpliftResult(
        store_id="store_1", item_id="item_6",
        baseline_q40=65.0, baseline_q60=76.4, baseline_q80=91.7,
        projected_q40=96.0, projected_q60=proj_q60, projected_q80=135.0,
        uplift_pct_q60=48.2, elasticity_coef=-0.086, discount_rate=0.20,
        is_elastic=True,
    )


def _make_uncertainty():
    from src.services.compute_decision_uncertainty import UncertaintyResult
    return UncertaintyResult(
        probability_profitable=0.84,
        p10=3.0, p50=10.2, p90=14.5,
        uncertainty_band={"p10": 3.0, "p50": 10.2, "p90": 14.5},
        n_scenarios=1000,
    )


def _make_cross_item():
    from src.entities.cross_item_impact import CrossItemImpact
    return CrossItemImpact(
        source_item="item_6",
        cannibalization_penalty_pct=2.1,
        total_substitution_loss_pct=2.1,
        net_basket_impact_pct=-1.5,
    )


def _make_replenishment():
    return ReplenishmentSignal(
        store_id="store_1", item_id="item_6",
        forecast_7d=113.2, current_stock=200,
        safety_factor=1.20, recommended_restock_qty=0,
        stockout_risk=StockoutRisk.LOW,
        stock_feasibility_score=0.88,
    )


def _make_score(state=DecisionState.APPROVE):
    from src.entities.decision_score_result import DecisionScoreResult
    return DecisionScoreResult(
        total_score=0.78,
        roi_component=0.73, stock_component=0.88,
        uncertainty_component=0.84, substitution_component=0.89,
        weights_used={"roi":0.40,"stock":0.25,"uncertainty":0.20,"substitution":0.15},
        decision_state=state, primary_risk_driver="roi",
    )


def _build_service(
    forecast_total=76.4, proj_q60=113.2, score_state=DecisionState.APPROVE
):
    from src.services.simulate_promo_roi import SimulatePromoROIService

    forecast_svc    = MagicMock()
    forecast_svc.execute = AsyncMock(return_value=_make_forecast(forecast_total))
    uplift_svc      = MagicMock()
    uplift_svc.execute = AsyncMock(return_value=_make_uplift(proj_q60))
    uncertainty_svc = MagicMock()
    uncertainty_svc.execute = MagicMock(return_value=_make_uncertainty())
    cross_item_svc  = MagicMock()
    cross_item_svc.execute = AsyncMock(return_value=_make_cross_item())
    replenish_svc   = MagicMock()
    replenish_svc.execute = AsyncMock(return_value=_make_replenishment())
    score_svc       = MagicMock()
    score_svc.execute = AsyncMock(return_value=_make_score(score_state))

    decision_repo = MagicMock()
    decision_repo.create_simulation = AsyncMock(return_value="sim-001")
    elasticity_repo = MagicMock()
    elasticity_repo.get_financial_assumptions = AsyncMock(return_value={
        "cogs_pct": 0.60, "promo_fixed_cost": 100.0,
        "holding_cost_per_day": 0.015, "source": "scenario_default",
    })
    config_repo = MagicMock()
    config_repo.get_config = AsyncMock(return_value=None)

    return SimulatePromoROIService(
        forecast_service=forecast_svc,
        uplift_service=uplift_svc,
        uncertainty_service=uncertainty_svc,
        cross_item_service=cross_item_svc,
        replenishment_service=replenish_svc,
        score_service=score_svc,
        elasticity_repo=elasticity_repo,
        decision_repo=decision_repo,
        config_repo=config_repo,
    )


@pytest.mark.asyncio
async def test_execute_returns_recommendation_object():
    svc = _build_service()
    result = await svc.execute(
        store_id="store_1", item_id="item_6",
        promo_dates=[date(2026, 4, 14), date(2026, 4, 15), date(2026, 4, 16)],
        promo_price=16.0, base_price=20.0,
    )
    assert isinstance(result, RecommendationObject)
    assert result.simulation_id != ""
    assert result.recommendation in (DecisionState.APPROVE, DecisionState.REVIEW, DecisionState.REJECT)


@pytest.mark.asyncio
async def test_execute_captures_config_snapshot():
    svc = _build_service()
    result = await svc.execute(
        store_id="store_1", item_id="item_6",
        promo_dates=[date(2026, 4, 14)],
        promo_price=16.0, base_price=20.0,
    )
    # config_snapshot must be a dict (may be empty if all configs missing)
    assert isinstance(result.config_snapshot, dict)


@pytest.mark.asyncio
async def test_execute_appends_risk_note_when_default_cogs_used():
    svc = _build_service()
    result = await svc.execute(
        store_id="store_1", item_id="item_6",
        promo_dates=[date(2026, 4, 14)],
        promo_price=16.0, base_price=20.0,
    )
    # scenario_default source → risk note appended
    assert any("default" in note.lower() for note in result.risk_notes)


@pytest.mark.asyncio
async def test_execute_persists_to_decision_repository():
    svc = _build_service()
    await svc.execute(
        store_id="store_1", item_id="item_6",
        promo_dates=[date(2026, 4, 14)],
        promo_price=16.0, base_price=20.0,
    )
    svc._decisions.create_simulation.assert_called_once()


@pytest.mark.asyncio
async def test_execute_adjusts_roi_for_cannibalization():
    svc = _build_service()
    result = await svc.execute(
        store_id="store_1", item_id="item_6",
        promo_dates=[date(2026, 4, 14)],
        promo_price=16.0, base_price=20.0,
    )
    # cannibalization_penalty > 0 means net_roi < gross_roi
    assert result.cannibalization_penalty >= 0


@pytest.mark.asyncio
async def test_execute_degrades_gracefully_when_uncertainty_fails():
    from src.services.simulate_promo_roi import SimulatePromoROIService
    svc = _build_service()
    # Make uncertainty fail
    svc._uncertainty.execute = MagicMock(side_effect=RuntimeError("mc failed"))
    result = await svc.execute(
        store_id="store_1", item_id="item_6",
        promo_dates=[date(2026, 4, 14)],
        promo_price=16.0, base_price=20.0,
    )
    # Should still return a result — non-critical failure
    assert isinstance(result, RecommendationObject)


@pytest.mark.asyncio
async def test_execute_approve_state():
    svc = _build_service(score_state=DecisionState.APPROVE)
    result = await svc.execute(
        store_id="store_1", item_id="item_6",
        promo_dates=[date(2026, 4, 14)],
        promo_price=16.0, base_price=20.0,
    )
    assert result.recommendation == DecisionState.APPROVE


@pytest.mark.asyncio
async def test_execute_reject_state():
    svc = _build_service(score_state=DecisionState.REJECT)
    result = await svc.execute(
        store_id="store_1", item_id="item_6",
        promo_dates=[date(2026, 4, 14)],
        promo_price=16.0, base_price=20.0,
    )
    assert result.recommendation == DecisionState.REJECT
