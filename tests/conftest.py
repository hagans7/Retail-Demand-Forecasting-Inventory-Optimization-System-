"""Shared pytest fixtures.

Fixtures are scope-sensitive:
    function scope (default): fresh mock per test
    module scope: shared within test file (use for DB connections)

"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.entities.forecast import ColdStartTier, DailyForecast, ForecastResult
from src.entities.recommendation_object import DecisionState, RecommendationObject
from src.entities.replenishment import ReplenishmentSignal, StockoutRisk


# ── Forecast fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def sample_daily_forecast():
    return DailyForecast(
        date=date(2026, 4, 14),
        predicted_sales=28.5,
        lower_bound=24.2,
        upper_bound=34.1,
        revenue_estimate=570.0,
        feature_snapshot={"lag_7": 27.0, "rolling_mean_28": 26.5},
    )


@pytest.fixture
def sample_forecast_result(sample_daily_forecast):
    return ForecastResult(
        store_id="store_1",
        item_id="item_1",
        horizon_days=7,
        daily_forecasts=[
            DailyForecast(
                date=date(2026, 4, 14) + __import__("datetime").timedelta(days=i),
                predicted_sales=28.5 + i,
                lower_bound=24.0,
                upper_bound=34.0,
            )
            for i in range(7)
        ],
        model_version="v1_test_q60",
        cold_start_tier=ColdStartTier.NONE,
        generated_at=datetime.now(tz=timezone.utc).isoformat(),
    )


@pytest.fixture
def cold_start_forecast_result():
    return ForecastResult(
        store_id="store_new",
        item_id="item_new",
        horizon_days=7,
        daily_forecasts=[
            DailyForecast(
                date=date(2026, 4, 14) + __import__("datetime").timedelta(days=i),
                predicted_sales=27.76,
                lower_bound=19.4,
                upper_bound=36.1,
            )
            for i in range(7)
        ],
        model_version="COLD_START_TIER1",
        cold_start_tier=ColdStartTier.TIER1_PROXY,
    )


# ── Replenishment fixture ──────────────────────────────────────────────────────

@pytest.fixture
def sample_replenishment():
    return ReplenishmentSignal(
        store_id="store_1", item_id="item_1",
        forecast_7d=200.0, current_stock=150,
        safety_factor=1.20,
        recommended_restock_qty=90,
        stockout_risk=StockoutRisk.MEDIUM,
        stock_feasibility_score=0.75,
    )


# ── V2 recommendation fixture ─────────────────────────────────────────────────

@pytest.fixture
def sample_recommendation():
    return RecommendationObject(
        simulation_id="sim-test-001",
        store_id="store_1", item_id="item_6",
        recommendation=DecisionState.APPROVE,
        decision_score=0.78,
        expected_roi=10.2, probability_profitable=0.84,
        uncertainty_band={"p10": 3.0, "p50": 10.2, "p90": 14.5},
        baseline_forecast=76.4, promo_forecast=113.2,
        expected_uplift_units=36.8, expected_uplift_pct=48.2,
        revenue_uplift_pct=18.5, revenue_roi_pct=18.5, net_roi_pct=10.2,
        cannibalization_penalty=2.1,
        config_snapshot={"DECISION_WEIGHTS": {"roi": 0.40}},
        risk_notes=["Using default COGS assumption"],
    )


# ── Mock repository fixtures ──────────────────────────────────────────────────

@pytest.fixture
def mock_config_repo():
    repo = MagicMock()
    repo.get_config = AsyncMock(return_value=None)
    repo.upsert_config = AsyncMock(return_value=None)
    repo.get_all_configs = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_decision_repo():
    repo = MagicMock()
    repo.create_simulation = AsyncMock(return_value="sim-001")
    repo.get_pending_feedback = AsyncMock(return_value=[])
    repo.update_resolution = AsyncMock(return_value=None)
    repo.get_simulation_drift_metrics = AsyncMock(return_value={
        "n_simulations": 10, "n_resolved": 8,
        "override_rate": 0.10, "approval_success_rate": 0.80,
    })
    return repo


@pytest.fixture
def mock_elasticity_repo():
    repo = MagicMock()
    repo.get_elasticity = AsyncMock(return_value=None)
    repo.update_elasticity_ema = AsyncMock(return_value=None)
    repo.get_financial_assumptions = AsyncMock(return_value={
        "cogs_pct": 0.60, "promo_fixed_cost": 100.0,
        "holding_cost_per_day": 0.015, "source": "scenario_default",
    })
    return repo
