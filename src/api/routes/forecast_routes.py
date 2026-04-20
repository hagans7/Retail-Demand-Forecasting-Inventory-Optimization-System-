"""Forecast routes — POST /forecast/, /confidence, /explain, /override."""
from __future__ import annotations

import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin123")
os.environ.setdefault("MODEL_STORE_BUCKET", "ml-models")

from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.core.exceptions.app_exceptions import (
    FeatureStoreUnavailableError,
    NoProductionModelError,
)
from src.core.logging.logger import get_logger

router = APIRouter(prefix="/forecast", tags=["Forecast"])
_logger = get_logger(__name__)


# ── Schemas ────────────────────────────────────────────────────────────────────

class ForecastRequest(BaseModel):
    """7-day demand forecast request.

    promo_plan: 1=promo active, 0=no promo, for each of 7 days.
    price_plan: expected price per day (used for revenue_estimate).
    """
    store_id  : str
    item_id   : str
    promo_plan: list[int]   = Field(..., min_length=7, max_length=7,
                                    description="1=promo, 0=no promo for next 7 days")
    price_plan: list[float] = Field(..., min_length=7, max_length=7,
                                    description="Price per day for next 7 days")


class DailyForecastOut(BaseModel):
    model_config = {"protected_namespaces": ()}
    date             : date
    predicted_sales  : float
    lower_bound      : float
    upper_bound      : float
    revenue_estimate : float | None = None


class ForecastResponse(BaseModel):
    model_config = {"protected_namespaces": ()}
    store_id        : str
    item_id         : str
    forecast        : list[DailyForecastOut]
    total_7d_demand : float
    peak_day        : date
    cold_start_tier : str
    confidence_label: str
    model_version   : str
    generated_at    : str


class ConfidenceRequest(BaseModel):
    store_id  : str
    item_id   : str
    promo_plan: list[int]   = Field(..., min_length=7, max_length=7)
    price_plan: list[float] = Field(..., min_length=7, max_length=7)


class DailyBandOut(BaseModel):
    date              : date
    lower_bound       : float
    central           : float
    upper_bound       : float
    uncertainty_label : str


class ConfidenceResponse(BaseModel):
    model_config = {"protected_namespaces": ()}
    store_id   : str
    item_id    : str
    version_tag: str
    bands      : list[DailyBandOut]


class ExplainRequest(BaseModel):
    store_id   : str
    item_id    : str
    target_date: date
    promo      : int   = Field(0, ge=0, le=1)
    price      : float = Field(20.0, gt=0)


class DriverOut(BaseModel):
    label      : str
    impact     : float
    direction  : str


class ExplainResponse(BaseModel):
    store_id       : str
    item_id        : str
    target_date    : date
    base_value     : float
    final_forecast : float
    top_positive   : list[DriverOut]
    top_negative   : list[DriverOut]


class OverrideRequest(BaseModel):
    store_id    : str
    item_id     : str
    target_date : date
    override_qty: int   = Field(..., ge=0)
    reason      : str   = Field(..., min_length=10)
    user_id     : str   = Field(..., min_length=1)


class OverrideResponse(BaseModel):
    event_id      : str
    store_id      : str
    item_id       : str
    target_date   : date
    override_qty  : int
    reason        : str
    system_value  : float | None


# ── Helper: build services ─────────────────────────────────────────────────────

def _build_forecast_service():
    from src.providers.infrastructure import get_model_client, get_storage_client, _session_factory, get_redis_client
    from src.repositories.feature_repository import FeatureRepository
    from src.repositories.model_registry_repository import ModelRegistryRepository
    from src.repositories.forecast_repository import ForecastRepository
    from src.repositories.config_repository import ConfigRepository
    from src.services.handle_cold_start import HandleColdStartService
    from src.services.generate_forecast import GenerateForecastService
    import redis.asyncio as aioredis

    # Note: in production these are proper FastAPI Depends; here simplified for route handler
    raise NotImplementedError("Use Depends pattern in full DI wiring")


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/", response_model=ForecastResponse,
             summary="Generate 7-day demand forecast")
async def generate_forecast(request: ForecastRequest) -> ForecastResponse:
    """Generate 7-day ahead demand forecast for a store-item pair.

    Cold start routing is transparent:
        history < 7 days  → TIER1_PROXY (cross-store average, error ~1.13×)
        history 7-27 days → TIER2_REDUCED (lag_7 only, error ~1.01×)
        history >= 28 days→ NONE (full model, MAE_promo ~2.641)

    Returns confidence_label: HIGH / MEDIUM / LOW based on cold_start_tier.
    revenue_estimate = predicted_sales × price_plan[day].

    HTTP 503 if no production model registered or feature store unavailable.
    """
    from datetime import timedelta
    from src.providers.infrastructure import _session_factory, get_model_client, get_storage_client
    from src.repositories.feature_repository import FeatureRepository
    from src.repositories.model_registry_repository import ModelRegistryRepository
    from src.repositories.forecast_repository import ForecastRepository
    from src.repositories.config_repository import ConfigRepository
    from src.services.handle_cold_start import HandleColdStartService
    from src.services.generate_forecast import GenerateForecastService
    import redis.asyncio as aioredis

    today       = date.today()
    target_dates= [today + timedelta(days=i) for i in range(7)]

    try:
        async with _session_factory() as db:
            redis  = aioredis.from_url("redis://localhost:6379/0", decode_responses=True)
            model  = get_model_client()
            feat   = FeatureRepository(db)
            reg    = ModelRegistryRepository(db)
            fc_rep = ForecastRepository(db)
            cfg    = ConfigRepository(db, redis)
            cs     = HandleColdStartService(model, feat, reg)
            svc    = GenerateForecastService(model, feat, reg, fc_rep, cs)
            result = await svc.execute(
                store_id=request.store_id,
                item_id=request.item_id,
                target_dates=target_dates,
                promo_plan=request.promo_plan,
                price_plan=request.price_plan,
            )
    except (NoProductionModelError, FeatureStoreUnavailableError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        _logger.error("Forecast error", exc_info=True,
                      extra={"store_id": request.store_id, "item_id": request.item_id})
        raise HTTPException(status_code=500, detail="Internal forecast error.")

    return ForecastResponse(
        store_id=result.store_id, item_id=result.item_id,
        forecast=[
            DailyForecastOut(
                date=d.date, predicted_sales=d.predicted_sales,
                lower_bound=d.lower_bound, upper_bound=d.upper_bound,
                revenue_estimate=d.revenue_estimate,
            )
            for d in result.daily_forecasts
        ],
        total_7d_demand=round(result.total_7d_demand(), 2),
        peak_day=result.peak_day().date,
        cold_start_tier=result.cold_start_tier.value,
        confidence_label=result.confidence_label(),
        model_version=result.model_version,
        generated_at=result.generated_at,
    )


@router.post("/confidence", response_model=ConfidenceResponse,
             summary="3-quantile prediction confidence bands")
async def get_forecast_confidence(request: ConfidenceRequest) -> ConfidenceResponse:
    """Return q40/q60/q80 prediction bands for uncertainty quantification.

    Loads all 3 quantile model artifacts (same version_tag as production q60).
    uncertainty_label: NARROW (<30% relative width) / MODERATE / WIDE (>80%).
    HTTP 503 if models unavailable.
    """
    from datetime import timedelta
    from src.providers.infrastructure import _session_factory, get_model_client
    from src.repositories.feature_repository import FeatureRepository
    from src.repositories.model_registry_repository import ModelRegistryRepository
    from src.services.get_forecast_confidence import GetForecastConfidenceService

    today        = date.today()
    target_dates = [today + timedelta(days=i) for i in range(7)]

    try:
        async with _session_factory() as db:
            model  = get_model_client()
            svc    = GetForecastConfidenceService(model, FeatureRepository(db), ModelRegistryRepository(db))
            result = await svc.execute(
                store_id=request.store_id, item_id=request.item_id,
                target_dates=target_dates,
                promo_plan=request.promo_plan, price_plan=request.price_plan,
            )
    except (NoProductionModelError, FeatureStoreUnavailableError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        _logger.error("Confidence error", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal confidence error.")

    return ConfidenceResponse(
        store_id=result.store_id, item_id=result.item_id,
        version_tag=result.version_tag,
        bands=[
            DailyBandOut(
                date=b.date, lower_bound=b.lower_bound, central=b.central,
                upper_bound=b.upper_bound, uncertainty_label=b.uncertainty_label,
            )
            for b in result.daily_bands
        ],
    )


@router.post("/explain", response_model=ExplainResponse,
             summary="SHAP feature driver explanation in business language")
async def explain_forecast(request: ExplainRequest) -> ExplainResponse:
    """SHAP-based explanation of what drives the forecast for a specific day.

    Translates feature names to business language via FEATURE_BUSINESS_LABELS.
    Returns top 3 positive and top 2 negative driver features.
    HTTP 503 if model unavailable.
    """
    from src.providers.infrastructure import _session_factory, get_model_client
    from src.repositories.feature_repository import FeatureRepository
    from src.repositories.model_registry_repository import ModelRegistryRepository
    from src.services.explain_forecast import ExplainForecastService

    try:
        async with _session_factory() as db:
            model = get_model_client()
            svc   = ExplainForecastService(model, FeatureRepository(db), ModelRegistryRepository(db))
            result= await svc.execute(
                store_id=request.store_id, item_id=request.item_id,
                target_date=request.target_date,
                promo=request.promo, price=request.price,
            )
    except (NoProductionModelError, FeatureStoreUnavailableError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        _logger.error("Explain error", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal explain error.")

    return ExplainResponse(
        store_id=result.store_id, item_id=result.item_id,
        target_date=result.target_date, base_value=result.base_value,
        final_forecast=result.final_forecast,
        top_positive=[DriverOut(label=d.label, impact=d.impact, direction=d.direction)
                      for d in result.top_positive_drivers()],
        top_negative=[DriverOut(label=d.label, impact=d.impact, direction=d.direction)
                      for d in result.top_negative_drivers()],
    )


@router.post("/override", response_model=OverrideResponse,
             summary="Human planner override of model forecast")
async def override_forecast(request: OverrideRequest) -> OverrideResponse:
    """Record a manual forecast override from a human planner.

    Stores the system recommendation and human override for audit trail.
    override_reason requires minimum 10 characters.
    Override is NOT applied to the model — recorded only.
    """
    from src.providers.infrastructure import _session_factory
    from src.repositories.forecast_repository import ForecastRepository
    from src.services.override_forecast import OverrideForecastService

    async with _session_factory() as db:
        svc   = OverrideForecastService(ForecastRepository(db))
        event = await svc.execute(
            store_id=request.store_id, item_id=request.item_id,
            target_date=request.target_date,
            override_qty=request.override_qty,
            reason=request.reason, user_id=request.user_id,
        )

    sys_val = event.system_recommendation.get("predicted_sales")
    return OverrideResponse(
        event_id=event.event_id, store_id=event.store_id, item_id=event.item_id,
        target_date=request.target_date, override_qty=request.override_qty,
        reason=event.override_reason,
        system_value=float(sys_val) if sys_val is not None else None,
    )
