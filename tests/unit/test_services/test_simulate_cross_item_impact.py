"""Tests — SimulateCrossItemImpactService."""
from __future__ import annotations

import pytest

from src.entities.cross_item_impact import ItemRelationship
from src.services.simulate_cross_item_impact import SimulateCrossItemImpactService


@pytest.fixture
def svc():
    return SimulateCrossItemImpactService()


@pytest.fixture
def corr_matrix():
    return {
        "item_6": {
            "item_12": 0.71,    # COMPLEMENTARY
            "item_23": -0.45,   # SUBSTITUTE
            "item_30": 0.05,    # INDEPENDENT
        }
    }


@pytest.fixture
def avg_sales():
    return {"item_6": 76.4, "item_12": 50.0, "item_23": 60.0, "item_30": 40.0}


@pytest.mark.asyncio
async def test_substitute_generates_loss(svc, corr_matrix, avg_sales):
    result = await svc.execute(
        "store_1", "item_6", discount_rate=0.20, uplift_pct=48.2,
        correlation_matrix=corr_matrix, avg_daily_sales=avg_sales,
    )
    assert result.total_substitution_loss_pct > 0
    assert result.n_substitutes == 1


@pytest.mark.asyncio
async def test_complementary_generates_gain(svc, corr_matrix, avg_sales):
    result = await svc.execute(
        "store_1", "item_6", discount_rate=0.20, uplift_pct=48.2,
        correlation_matrix=corr_matrix, avg_daily_sales=avg_sales,
    )
    assert result.total_halo_gain_pct > 0
    assert result.n_complements == 1


@pytest.mark.asyncio
async def test_independent_items_have_zero_impact(svc, avg_sales):
    """Only independent items → zero impact."""
    corr_only_independent = {"item_6": {"item_30": 0.05, "item_31": 0.02}}
    result = await svc.execute(
        "store_1", "item_6", discount_rate=0.20, uplift_pct=48.2,
        correlation_matrix=corr_only_independent, avg_daily_sales=avg_sales,
    )
    assert result.cannibalization_penalty_pct == 0.0
    assert result.total_halo_gain_pct == 0.0
    assert len(result.impacted_items) == 0


@pytest.mark.asyncio
async def test_none_correlation_returns_zero_impact(svc):
    result = await svc.execute(
        "store_1", "item_6", discount_rate=0.20, uplift_pct=48.2,
        correlation_matrix=None,
    )
    assert result.cannibalization_penalty_pct == 0.0
    assert result.source_item == "item_6"


@pytest.mark.asyncio
async def test_cannibalization_penalty_from_substitutes_only(svc, corr_matrix, avg_sales):
    result = await svc.execute(
        "store_1", "item_6", discount_rate=0.20, uplift_pct=48.2,
        correlation_matrix=corr_matrix, avg_daily_sales=avg_sales,
    )
    # cannibalization_penalty == substitution_loss (not net basket)
    assert result.cannibalization_penalty_pct == result.total_substitution_loss_pct


@pytest.mark.asyncio
async def test_significant_cannibalization_detected(svc):
    """High-correlation substitute with dominant sales → penalty > 5% threshold."""
    # item_23 has 100× sales of item_6 to ensure penalty crosses 5.0% threshold.
    # penalty = (100*7 * 0.90 * 0.30 * 0.5) / ((1+100)*7) * 100 = 13.4%
    high_sub = {"item_6": {"item_23": -0.90}}
    small_basket = {"item_6": 1.0, "item_23": 100.0}
    result = await svc.execute(
        "store_1", "item_6", discount_rate=0.30, uplift_pct=60.0,
        correlation_matrix=high_sub, avg_daily_sales=small_basket,
    )
    assert result.has_significant_cannibalization() is True, (
        f"penalty={result.cannibalization_penalty_pct:.2f}% must exceed 5.0% threshold"
    )


@pytest.mark.asyncio
async def test_source_item_not_in_own_impacted_items(svc, corr_matrix, avg_sales):
    result = await svc.execute(
        "store_1", "item_6", discount_rate=0.20, uplift_pct=48.2,
        correlation_matrix=corr_matrix, avg_daily_sales=avg_sales,
    )
    item_ids = [i["item_id"] for i in result.impacted_items]
    assert "item_6" not in item_ids
