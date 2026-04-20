"""Simulation routes — /simulate-promo/ and /simulate-promo/roi (V2)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from src.core.exceptions.app_exceptions import (
    FeatureStoreUnavailableError,
    NoProductionModelError,
)
from src.core.logging.logger import get_logger
from src.entities.recommendation_object import RecommendationObject
from src.providers.services import get_simulate_promo_roi_service

router = APIRouter(prefix="/simulate-promo", tags=["Decision Intelligence"])
_logger = get_logger(__name__)


# ------------------------------------------------------------------
# Request / Response schemas
# ------------------------------------------------------------------

class PromoROIRequest(BaseModel):
    """Full V2 Decision Intelligence simulation request.

    promo_price must be strictly less than base_price.
    promo_dates: max 14 days (2-week campaign window).
    cogs_pct: optional override (0.0-0.99). If omitted, reads from
              item_financial_assumptions or falls back to NORMAL_MARGIN.
    """
    store_id        : str
    item_id         : str
    promo_dates     : list[date] = Field(..., min_length=1, max_length=14)
    promo_price     : float      = Field(..., gt=0, description="Discounted price during promo")
    base_price      : float      = Field(..., gt=0, description="Normal baseline price")
    current_stock   : int        = Field(0, ge=0, description="Current units in warehouse")
    cogs_pct        : float | None = Field(None, ge=0.0, lt=1.0)
    promo_fixed_cost: float | None = Field(None, ge=0.0)

    @model_validator(mode="after")
    def promo_price_below_base(self):
        if self.promo_price >= self.base_price:
            raise ValueError("promo_price must be strictly less than base_price")
        return self


class UncertaintyBandOut(BaseModel):
    p10: float
    p50: float
    p90: float


class RecommendationResponse(BaseModel):
    model_config = {"protected_namespaces": ()}
    """V2 Decision Intelligence recommendation output.

    recommendation: APPROVE / REVIEW / REJECT (all return HTTP 200).
    config_snapshot: frozen parameter set used for this simulation.
    override_allowed: always True — system is decision support only.
    """
    simulation_id          : str
    store_id               : str
    item_id                : str
    recommendation         : str
    decision_score         : float
    expected_roi           : float
    probability_profitable : float
    uncertainty_band       : UncertaintyBandOut
    baseline_forecast      : float
    promo_forecast         : float
    expected_uplift_units  : float
    expected_uplift_pct    : float
    revenue_uplift_pct     : float
    revenue_roi_pct        : float
    net_roi_pct            : float
    cannibalization_penalty: float
    impacted_items         : list[dict] = []
    additional_stock_needed: int
    stock_feasible         : bool
    risk_notes             : list[str]
    recommended_action     : str | None
    override_allowed       : bool = True
    config_snapshot        : dict
    cogs_source            : str
    model_version          : str
    cold_start_tier        : str
    generated_at           : str


def _map_to_response(obj: RecommendationObject) -> RecommendationResponse:
    ub = obj.uncertainty_band or {}
    return RecommendationResponse(
        simulation_id=obj.simulation_id,
        store_id=obj.store_id,
        item_id=obj.item_id,
        recommendation=obj.recommendation.value,
        decision_score=obj.decision_score,
        expected_roi=obj.expected_roi,
        probability_profitable=obj.probability_profitable,
        uncertainty_band=UncertaintyBandOut(
            p10=ub.get("p10", 0.0),
            p50=ub.get("p50", 0.0),
            p90=ub.get("p90", 0.0),
        ),
        baseline_forecast=obj.baseline_forecast,
        promo_forecast=obj.promo_forecast,
        expected_uplift_units=obj.expected_uplift_units,
        expected_uplift_pct=obj.expected_uplift_pct,
        revenue_uplift_pct=obj.revenue_uplift_pct,
        revenue_roi_pct=obj.revenue_roi_pct,
        net_roi_pct=obj.net_roi_pct,
        cannibalization_penalty=obj.cannibalization_penalty,
        impacted_items=obj.impacted_items,
        additional_stock_needed=obj.additional_stock_needed,
        stock_feasible=obj.stock_feasible,
        risk_notes=obj.risk_notes,
        recommended_action=obj.recommended_action,
        config_snapshot=obj.config_snapshot,
        cogs_source=obj.cogs_source,
        model_version=obj.model_version,
        cold_start_tier=obj.cold_start_tier,
        generated_at=obj.created_at.isoformat() if obj.created_at else "",
    )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post(
    "/roi",
    response_model=RecommendationResponse,
    summary="Full V2 Decision Intelligence simulation",
    responses={
        200: {"description": "Recommendation generated (APPROVE/REVIEW/REJECT all return 200)"},
        422: {"description": "Validation error — promo_price >= base_price or missing field"},
        503: {"description": "Forecast service unavailable"},
    },
)
async def simulate_promo_roi(
    request: PromoROIRequest,
    service=Depends(get_simulate_promo_roi_service),
) -> RecommendationResponse:
    """Full V2 pipeline: forecast → uplift → profit → uncertainty → cannibalization → score → recommendation.

    Response includes config_snapshot for audit reproducibility.
    All decisions are persisted for feedback recalibration.
    APPROVE/REVIEW/REJECT all return HTTP 200 — human override always allowed.
    """
    _logger.info(
        "POST /simulate-promo/roi",
        extra={
            "store_id": request.store_id, "item_id": request.item_id,
            "n_promo_dates": len(request.promo_dates),
            "operation": "simulate_promo_roi_endpoint",
        },
    )
    try:
        result = await service.execute(
            store_id=request.store_id,
            item_id=request.item_id,
            promo_dates=request.promo_dates,
            promo_price=request.promo_price,
            base_price=request.base_price,
            current_stock=request.current_stock,
            cogs_pct=request.cogs_pct,
            promo_fixed_cost=request.promo_fixed_cost,
        )
        return _map_to_response(result)
    except (NoProductionModelError, FeatureStoreUnavailableError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        _logger.error(
            "Unexpected error in /simulate-promo/roi",
            exc_info=True,
            extra={"store_id": request.store_id, "item_id": request.item_id},
        )
        raise HTTPException(status_code=500, detail="Internal simulation error.")


# ── POST /simulate-promo/ — V1 basic simulation (without full ROI pipeline) ──

class BasicPromoRequest(BaseModel):
    """Basic V1 promo simulation — uplift projection without full ROI pipeline."""
    store_id  : str
    item_id   : str
    promo_dates : list[date] = Field(..., min_length=1, max_length=14)
    promo_price : float = Field(..., gt=0)
    base_price  : float = Field(..., gt=0)

    @model_validator(mode="after")
    def price_check(self):
        if self.promo_price >= self.base_price:
            raise ValueError("promo_price must be less than base_price")
        return self


class BasicPromoResponse(BaseModel):
    model_config = {"protected_namespaces": ()}
    store_id              : str
    item_id               : str
    baseline_forecast     : float
    promo_forecast        : float
    expected_uplift_units : float
    expected_uplift_pct   : float
    revenue_uplift_pct    : float
    breakeven_uplift_pct  : float
    is_revenue_positive   : bool
    discount_rate         : float
    model_version         : str


@router.post("/", response_model=BasicPromoResponse,
             summary="Basic V1 promo simulation (uplift only, no ROI/COGS)")
async def simulate_promo_basic(
    request: BasicPromoRequest,
    service=Depends(get_simulate_promo_roi_service),
) -> BasicPromoResponse:
    """V1-compatible promo simulation — returns uplift projection without full ROI pipeline.

    Lighter than /simulate-promo/roi: no Monte Carlo, no COGS calculation, no DB persistence.
    Use /simulate-promo/roi for the full Decision Intelligence recommendation.

    discount_rate = (base_price - promo_price) / base_price
    breakeven_uplift_pct = 1 / (1 - discount_rate) - 1  (revenue break-even threshold)
    """
    from src.providers.infrastructure import _session_factory, get_model_client
    from src.repositories.feature_repository import FeatureRepository
    from src.repositories.model_registry_repository import ModelRegistryRepository
    from src.repositories.forecast_repository import ForecastRepository
    from src.repositories.config_repository import ConfigRepository
    from src.repositories.elasticity_repository import ElasticityRepository
    from src.services.handle_cold_start import HandleColdStartService
    from src.services.generate_forecast import GenerateForecastService
    from src.services.simulate_promo_uplift import SimulatePromoUpliftService
    from src.core.constants.analytics_constants import PROMO_BREAKEVEN_UPLIFT_PCT
    import redis.asyncio as aioredis
    from datetime import timedelta, date as dt

    today = dt.today()
    target_dates = [today + timedelta(days=i) for i in range(len(request.promo_dates))]

    try:
        async with _session_factory() as db:
            redis   = aioredis.from_url("redis://localhost:6379/0", decode_responses=True)
            model   = get_model_client()
            feat    = FeatureRepository(db)
            reg     = ModelRegistryRepository(db)
            fc_rep  = ForecastRepository(db)
            cfg     = ConfigRepository(db, redis)
            elast   = ElasticityRepository(db)
            cs      = HandleColdStartService(model, feat, reg)
            fc_svc  = GenerateForecastService(model, feat, reg, fc_rep, cs)
            upl_svc = SimulatePromoUpliftService(model, feat, reg, elast)

            baseline_fc = await fc_svc.execute(
                request.store_id, request.item_id, target_dates,
                [0] * len(target_dates), [request.base_price] * len(target_dates),
            )
            promo_fc = await fc_svc.execute(
                request.store_id, request.item_id, target_dates,
                [1] * len(target_dates), [request.promo_price] * len(target_dates),
            )
            baseline_q60 = baseline_fc.total_7d_demand()
            promo_q60    = promo_fc.total_7d_demand()

            uplift = await upl_svc.execute(
                request.store_id, request.item_id, request.promo_dates,
                request.promo_price, request.base_price,
                baseline_q60 * 0.85, baseline_q60, baseline_q60 * 1.20,
            )
    except (NoProductionModelError, FeatureStoreUnavailableError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        _logger.error("Basic simulation error", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal simulation error.")

    discount_rate = uplift.discount_rate
    breakeven     = (1 / (1 - discount_rate) - 1) * 100 if discount_rate < 1 else 0.0
    rev_uplift    = uplift.uplift_pct_q60 - (discount_rate / (1 - discount_rate)) * 100

    return BasicPromoResponse(
        store_id=request.store_id, item_id=request.item_id,
        baseline_forecast=round(baseline_q60, 2),
        promo_forecast=round(uplift.projected_q60, 2),
        expected_uplift_units=round(uplift.projected_q60 - baseline_q60, 2),
        expected_uplift_pct=round(uplift.uplift_pct_q60, 2),
        revenue_uplift_pct=round(max(rev_uplift, 0), 2),
        breakeven_uplift_pct=round(breakeven, 2),
        is_revenue_positive=uplift.uplift_pct_q60 > breakeven,
        discount_rate=round(discount_rate, 4),
        model_version=baseline_fc.model_version,
    )
