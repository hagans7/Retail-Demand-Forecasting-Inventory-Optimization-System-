"""Integration tests — /simulate-promo/roi API endpoint.

Uses .env.test for settings. No real DB/Redis required (services are mocked).
"""
from __future__ import annotations

import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")
os.environ.setdefault("MODEL_STORE_BUCKET", "ml-models")

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.entities.recommendation_object import DecisionState, RecommendationObject


def _make_mock_recommendation(state=DecisionState.APPROVE):
    return RecommendationObject(
        simulation_id="sim-api-test-001",
        store_id="store_1", item_id="item_6",
        recommendation=state,
        decision_score=0.78, expected_roi=10.2, probability_profitable=0.84,
        uncertainty_band={"p10": 3.0, "p50": 10.2, "p90": 14.5},
        baseline_forecast=76.4, promo_forecast=113.2,
        expected_uplift_units=36.8, expected_uplift_pct=48.2,
        revenue_uplift_pct=18.5, revenue_roi_pct=18.5, net_roi_pct=10.2,
        cannibalization_penalty=2.1, additional_stock_needed=50,
        stock_feasible=True, risk_notes=["Using default COGS assumption"],
        config_snapshot={"DECISION_WEIGHTS": {"roi": 0.40}},
        cogs_source="scenario_default", model_version="v1_test",
        created_at=datetime.now(tz=timezone.utc),
    )


@pytest.fixture
def client():
    from src.main import app
    from src.providers.services import get_simulate_promo_roi_service

    mock_service = MagicMock()
    mock_service.execute = AsyncMock(return_value=_make_mock_recommendation())
    app.dependency_overrides[get_simulate_promo_roi_service] = lambda: mock_service

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def test_simulate_promo_roi_returns_200(client):
    response = client.post("/simulate-promo/roi", json={
        "store_id": "store_1", "item_id": "item_6",
        "promo_dates": ["2026-04-14", "2026-04-15", "2026-04-16"],
        "promo_price": 16.0, "base_price": 20.0, "current_stock": 200,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["simulation_id"] == "sim-api-test-001"
    assert data["recommendation"] in ("APPROVE", "REVIEW", "REJECT")


def test_simulate_promo_roi_includes_config_snapshot(client):
    response = client.post("/simulate-promo/roi", json={
        "store_id": "store_1", "item_id": "item_6",
        "promo_dates": ["2026-04-14"],
        "promo_price": 16.0, "base_price": 20.0,
    })
    assert response.status_code == 200
    assert isinstance(response.json()["config_snapshot"], dict)


def test_simulate_promo_roi_422_when_promo_price_above_base(client):
    """promo_price > base_price → Pydantic validator → 422."""
    response = client.post("/simulate-promo/roi", json={
        "store_id": "store_1", "item_id": "item_6",
        "promo_dates": ["2026-04-14"],
        "promo_price": 25.0, "base_price": 20.0,
    })
    assert response.status_code == 422


def test_simulate_promo_roi_422_when_promo_price_equals_base(client):
    """promo_price == base_price → Pydantic validator → 422."""
    response = client.post("/simulate-promo/roi", json={
        "store_id": "store_1", "item_id": "item_6",
        "promo_dates": ["2026-04-14"],
        "promo_price": 20.0, "base_price": 20.0,
    })
    assert response.status_code == 422


def test_simulate_promo_roi_returns_503_when_service_unavailable():
    """NoProductionModelError → 503."""
    import os
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    from src.main import app
    from src.providers.services import get_simulate_promo_roi_service
    from src.core.exceptions.app_exceptions import NoProductionModelError

    failing_service = MagicMock()
    failing_service.execute = AsyncMock(side_effect=NoProductionModelError("No model"))
    app.dependency_overrides[get_simulate_promo_roi_service] = lambda: failing_service

    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.post("/simulate-promo/roi", json={
            "store_id": "store_1", "item_id": "item_6",
            "promo_dates": ["2026-04-14"],
            "promo_price": 16.0, "base_price": 20.0,
        })
    app.dependency_overrides.clear()
    assert response.status_code == 503


def test_simulate_promo_roi_max_14_promo_dates(client):
    """More than 14 promo_dates → 422."""
    response = client.post("/simulate-promo/roi", json={
        "store_id": "store_1", "item_id": "item_6",
        "promo_dates": [f"2026-04-{14+i:02d}" for i in range(20)],
        "promo_price": 16.0, "base_price": 20.0,
    })
    assert response.status_code == 422
