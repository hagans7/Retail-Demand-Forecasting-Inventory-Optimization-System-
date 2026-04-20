"""Replenishment routes — POST /replenishment/."""
from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.core.exceptions.app_exceptions import (
    FeatureStoreUnavailableError,
    NoProductionModelError,
)
from src.core.logging.logger import get_logger

router = APIRouter(prefix="/replenishment", tags=["Replenishment"])
_logger = get_logger(__name__)


class ReplenishmentRequest(BaseModel):
    """Restock recommendation request.

    current_stock: units currently available in warehouse.
    promo_plan: 1=promo active, 0=none for each of next 7 days.
    price_plan: expected price per day.
    """
    store_id     : str
    item_id      : str
    current_stock: int          = Field(..., ge=0, description="Current units in warehouse")
    promo_plan   : list[int]   = Field(..., min_length=7, max_length=7)
    price_plan   : list[float] = Field(..., min_length=7, max_length=7)


class ReplenishmentResponse(BaseModel):
    """Restock recommendation response.

    stock_feasibility_score: 0.0-1.0 — consumed by V2 decision scoring.
    reason_codes: list of trigger flags (promo_planned, critical_stock_level, etc.)
    """
    store_id                : str
    item_id                 : str
    forecast_7d             : float
    current_stock           : int
    safety_factor           : float
    recommended_restock_qty : int
    stockout_risk           : str
    stock_feasibility_score : float
    days_of_stock_remaining : float
    coverage_gap_days       : float
    reason_codes            : list[str]
    cold_start_tier         : str


@router.post("/", response_model=ReplenishmentResponse,
             summary="Restock recommendation with inventory feasibility score")
async def compute_replenishment(request: ReplenishmentRequest) -> ReplenishmentResponse:
    """Compute restock recommendation for a store-item pair.

    Safety factor selection (Category 3 — DB-overridable via /config):
        cold_start pairs   → SAFETY_FACTOR_COLD_START (1.30 default)
        promo days         → SAFETY_FACTOR_PROMO (1.20 default)
        normal days        → SAFETY_FACTOR_NORMAL (1.10 default)

    stock_feasibility_score (0.0-1.0):
        1.0 = stock exceeds buffered requirement
        0.0 = no stock available at all
        Used by V2 /simulate-promo/roi as inventory constraint input.

    HTTP 503 if no production model or feature store unavailable.
    """
    from src.providers.infrastructure import _session_factory, get_model_client
    from src.repositories.feature_repository import FeatureRepository
    from src.repositories.model_registry_repository import ModelRegistryRepository
    from src.repositories.forecast_repository import ForecastRepository
    from src.repositories.config_repository import ConfigRepository
    from src.services.handle_cold_start import HandleColdStartService
    from src.services.generate_forecast import GenerateForecastService
    from src.services.compute_replenishment import ComputeReplenishmentService
    import redis.asyncio as aioredis

    try:
        async with _session_factory() as db:
            redis  = aioredis.from_url("redis://localhost:6379/0", decode_responses=True)
            model  = get_model_client()
            feat   = FeatureRepository(db)
            reg    = ModelRegistryRepository(db)
            fc_rep = ForecastRepository(db)
            cfg    = ConfigRepository(db, redis)
            cs     = HandleColdStartService(model, feat, reg)
            fc_svc = GenerateForecastService(model, feat, reg, fc_rep, cs)
            svc    = ComputeReplenishmentService(fc_svc, cfg)
            result = await svc.execute(
                store_id=request.store_id,
                item_id=request.item_id,
                current_stock=request.current_stock,
                promo_plan=request.promo_plan,
                price_plan=request.price_plan,
            )
    except (NoProductionModelError, FeatureStoreUnavailableError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        _logger.error("Replenishment error", exc_info=True,
                      extra={"store_id": request.store_id})
        raise HTTPException(status_code=500, detail="Internal replenishment error.")

    return ReplenishmentResponse(
        store_id=result.store_id, item_id=result.item_id,
        forecast_7d=result.forecast_7d,
        current_stock=result.current_stock,
        safety_factor=result.safety_factor,
        recommended_restock_qty=result.recommended_restock_qty,
        stockout_risk=result.stockout_risk.value,
        stock_feasibility_score=result.stock_feasibility_score,
        days_of_stock_remaining=round(result.days_of_stock_remaining(), 2),
        coverage_gap_days=round(result.coverage_gap(), 2),
        reason_codes=result.reason_codes,
        cold_start_tier=result.cold_start_tier,
    )
