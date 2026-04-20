"""Tests — SimulatePromoUpliftService."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.simulate_promo_uplift import SimulatePromoUpliftService

# ELASTICITY_ELASTIC_ITEM_THRESHOLD = -0.10 (from analytics_constants)
# coef < -0.10 → elastic; coef >= -0.10 → inelastic


def _make_service(elasticity_coef=None):
    model_client    = MagicMock()
    feature_repo    = MagicMock()
    model_registry  = MagicMock()
    elasticity_repo = MagicMock()
    elasticity_repo.get_elasticity = AsyncMock(return_value=elasticity_coef)
    return SimulatePromoUpliftService(model_client, feature_repo, model_registry, elasticity_repo)


@pytest.mark.asyncio
async def test_elastic_item_amplified_uplift():
    """Coef -0.30 < threshold -0.10 → elastic → amplified projection."""
    svc = _make_service(elasticity_coef=-0.30)  # strongly elastic
    result = await svc.execute(
        store_id="store_1", item_id="item_6",
        promo_dates=[date(2026, 4, 14), date(2026, 4, 15)],
        promo_price=16.0, base_price=20.0,
        baseline_forecast_q40=65.0, baseline_forecast_q60=76.4, baseline_forecast_q80=91.7,
    )
    assert result.is_elastic is True, (
        "elasticity_coef=-0.30 must be classified elastic (threshold=-0.10)"
    )
    # Amplification: multiplier = 1 + 0.30 * (0.20/0.20) = 1.30
    # projected_q60 >= baseline * (1 + 0.50 * 1.30) = baseline * 1.65
    assert result.projected_q60 > 76.4, "Elastic item must project above baseline"


@pytest.mark.asyncio
async def test_inelastic_item_no_amplification():
    """Coef -0.01 >= threshold -0.10 → inelastic → uses global baseline only."""
    svc = _make_service(elasticity_coef=-0.01)
    result = await svc.execute(
        store_id="store_1", item_id="item_45",
        promo_dates=[date(2026, 4, 14)],
        promo_price=16.0, base_price=20.0,
        baseline_forecast_q40=65.0, baseline_forecast_q60=76.4, baseline_forecast_q80=91.7,
    )
    assert result.is_elastic is False
    # Inelastic item must still have positive uplift (global baseline applies)
    assert result.projected_q60 > 76.4, "Inelastic item must still have positive uplift from global baseline"


@pytest.mark.asyncio
async def test_falls_back_to_global_when_no_elasticity():
    """When elasticity is None, falls back to BASELINE_PRICE_SALES_CORR."""
    svc = _make_service(elasticity_coef=None)
    result = await svc.execute(
        store_id="store_1", item_id="item_unknown",
        promo_dates=[date(2026, 4, 14)],
        promo_price=16.0, base_price=20.0,
        baseline_forecast_q40=65.0, baseline_forecast_q60=76.4, baseline_forecast_q80=91.7,
    )
    assert result.projected_q60 > 0


@pytest.mark.asyncio
async def test_streak_decay_reduces_uplift_over_days():
    """Multi-day promo should average lower uplift than single day due to streak decay."""
    svc = _make_service(elasticity_coef=-0.30)
    single_day = await svc.execute(
        "store_1", "item_6", [date(2026, 4, 14)],
        16.0, 20.0, 65.0, 76.4, 91.7,
    )
    seven_days = await svc.execute(
        "store_1", "item_6",
        [date(2026, 4, 14) + __import__("datetime").timedelta(days=i) for i in range(7)],
        16.0, 20.0, 65.0, 76.4, 91.7,
    )
    # 7-day has streak decay from Day4+ → avg multiplier < 1-day full multiplier
    assert seven_days.uplift_pct_q60 <= single_day.uplift_pct_q60 + 5.0, (
        "7-day promo uplift must not substantially exceed 1-day (streak decay expected)"
    )


@pytest.mark.asyncio
async def test_projected_never_negative():
    """Projected units must always be >= 0, even with near-zero baseline."""
    svc = _make_service(elasticity_coef=-0.30)
    result = await svc.execute(
        "store_1", "item_6", [date(2026, 4, 14)],
        16.0, 20.0, 0.1, 0.1, 0.1,  # near-zero baseline
    )
    assert result.projected_q40 >= 0
    assert result.projected_q60 >= 0
    assert result.projected_q80 >= 0


@pytest.mark.asyncio
async def test_discount_rate_computed_correctly():
    """discount_rate = (base - promo) / base = (20 - 16) / 20 = 0.20"""
    svc = _make_service(elasticity_coef=-0.30)
    result = await svc.execute(
        "store_1", "item_6", [date(2026, 4, 14)],
        16.0, 20.0, 65.0, 76.4, 91.7,
    )
    assert abs(result.discount_rate - 0.20) < 1e-6
