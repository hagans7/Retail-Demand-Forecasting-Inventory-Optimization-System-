"""Tests — ForecastResult entity invariants."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.entities.forecast import ColdStartTier, DailyForecast, ForecastResult


def _make_result(n_days=7, tier=ColdStartTier.NONE):
    dailies = [
        DailyForecast(
            date=date(2026, 4, 14) + timedelta(days=i),
            predicted_sales=float(20 + i),
            lower_bound=float(17 + i),
            upper_bound=float(25 + i),
        )
        for i in range(n_days)
    ]
    return ForecastResult(
        store_id="store_1", item_id="item_1",
        horizon_days=n_days, daily_forecasts=dailies,
        cold_start_tier=tier,
    )


def test_predicted_sales_never_negative():
    with pytest.raises(ValueError):
        DailyForecast(
            date=date(2026, 4, 14),
            predicted_sales=-1.0,
            lower_bound=-2.0, upper_bound=5.0,
        )


def test_horizon_mismatch_raises():
    with pytest.raises(ValueError):
        ForecastResult(
            store_id="s", item_id="i", horizon_days=7,
            daily_forecasts=[
                DailyForecast(date=date(2026,4,14), predicted_sales=10.0,
                              lower_bound=8.0, upper_bound=12.0)
            ],  # only 1 daily, horizon_days=7 → mismatch
        )


def test_total_7d_demand():
    r = _make_result()
    expected = sum(20 + i for i in range(7))
    assert abs(r.total_7d_demand() - expected) < 0.01


def test_peak_day_returns_highest():
    r = _make_result()
    peak = r.peak_day()
    assert peak.predicted_sales == max(d.predicted_sales for d in r.daily_forecasts)


def test_is_cold_start_true_for_tier1():
    r = _make_result(tier=ColdStartTier.TIER1_PROXY)
    assert r.is_cold_start() is True


def test_is_cold_start_false_for_none():
    r = _make_result(tier=ColdStartTier.NONE)
    assert r.is_cold_start() is False


def test_confidence_label_low_for_tier1():
    r = _make_result(tier=ColdStartTier.TIER1_PROXY)
    assert r.confidence_label() == "LOW"


def test_confidence_label_high_for_none():
    r = _make_result(tier=ColdStartTier.NONE)
    assert r.confidence_label() == "HIGH"


def test_has_promo_day_true():
    r = _make_result()
    promo_dates = [date(2026, 4, 15)]  # second day in forecast
    assert r.has_promo_day(promo_dates) is True


def test_has_promo_day_false():
    r = _make_result()
    assert r.has_promo_day([date(2026, 1, 1)]) is False
