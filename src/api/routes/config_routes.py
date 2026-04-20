"""Config routes — Category 3 runtime business rules.

GET  /config/business-rules   → read all params (public)
PATCH /config/business-rules  → update with admin auth + mandatory reason
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.core.constants.business_constants import SAFETY_BOUNDS
from src.core.exceptions.app_exceptions import ConfigSafetyBoundsViolationError
from src.core.logging.logger import get_logger
from src.entities.business_config import BusinessConfig
from src.interfaces.base_config_repository import BaseConfigRepository
from src.providers.repositories import get_config_repo

router = APIRouter(prefix="/config", tags=["Configuration"])
_logger = get_logger(__name__)

# Downstream effects — shown in PATCH response to inform operators
_CONFIG_DOWNSTREAM_EFFECTS: dict[str, list[str]] = {
    "SAFETY_FACTOR_PROMO":          ["replenishment_calculations", "risk_classification"],
    "SAFETY_FACTOR_NORMAL":         ["replenishment_calculations"],
    "SAFETY_FACTOR_COLD_START":     ["replenishment_calculations", "cold_start_routing"],
    "DECISION_WEIGHTS":             ["decision_scoring", "recommendation_state"],
    "DECISION_APPROVE_THRESHOLD":   ["recommendation_state", "approval_rate_metrics"],
    "DECISION_REVIEW_THRESHOLD":    ["recommendation_state"],
    "PROMO_UF_ALERT_THRESHOLD":     ["monitoring_alerts", "retraining_trigger"],
    "MAE_PROMO_DEGRADATION_PCT":    ["retraining_trigger"],
}


class BusinessRuleRead(BaseModel):
    config_key    : str
    config_value  : Any
    updated_by    : str
    updated_at    : str
    reason        : str


class BusinessRuleUpdate(BaseModel):
    """Update a single Category 3 runtime parameter.

    reason: mandatory (min 10 chars) — stored in audit trail forever.
    config_value: must be within SAFETY_BOUNDS for that key (HTTP 422 if not).
    """
    config_key   : str
    config_value : Any
    reason       : str = Field(..., min_length=10,
                               description="Mandatory rationale. Stored in audit trail.")


class BusinessRuleUpdateResponse(BaseModel):
    config_key        : str
    new_value         : Any
    previous_value    : Any
    updated_by        : str
    updated_at        : str
    effective_in      : str = "within 5 minutes (Redis TTL=300s)"
    downstream_effects: list[str] = []


@router.get("/business-rules", response_model=list[BusinessRuleRead])
async def get_all_configs(
    repo: BaseConfigRepository = Depends(get_config_repo),
) -> list[BusinessRuleRead]:
    """Return all Category 3 runtime parameters."""
    configs = await repo.get_all_configs()
    return [
        BusinessRuleRead(
            config_key=c.config_key,
            config_value=c.config_value,
            updated_by=c.updated_by,
            updated_at=c.updated_at.isoformat(),
            reason=c.reason,
        )
        for c in configs
    ]


@router.patch("/business-rules", response_model=BusinessRuleUpdateResponse)
async def update_config(
    update: BusinessRuleUpdate,
    repo: BaseConfigRepository = Depends(get_config_repo),
) -> BusinessRuleUpdateResponse:
    """Update a Category 3 runtime parameter.

    Changes take effect within 5 minutes (Redis TTL).
    Value must be within SAFETY_BOUNDS — HTTP 422 if exceeded.
    Requires admin authentication (TODO: add JWT middleware).
    """
    # Validate safety bounds
    key = update.config_key
    value = update.config_value
    if key in SAFETY_BOUNDS and isinstance(value, (int, float)):
        lo, hi = SAFETY_BOUNDS[key]
        if not (lo <= float(value) <= hi):
            raise HTTPException(
                status_code=422,
                detail=f"{key} value {value} outside safety bounds [{lo}, {hi}]"
            )

    # Read previous value for audit
    existing = await repo.get_config(key)
    prev_value = existing.config_value if existing else None

    config = BusinessConfig(
        config_key=key,
        config_value=value,
        config_type=type(value).__name__,
        updated_by="admin",   # TODO: extract from JWT
        updated_at=datetime.now(tz=timezone.utc),
        reason=update.reason,
        previous_value=prev_value,
    )
    await repo.upsert_config(config)
    effects = _CONFIG_DOWNSTREAM_EFFECTS.get(key, ["general_configuration"])

    _logger.info(
        "Business config updated",
        extra={
            "config_key": key, "new_value": value,
            "previous_value": prev_value, "reason": update.reason,
            "operation": "update_config",
        },
    )
    return BusinessRuleUpdateResponse(
        config_key=key,
        new_value=value,
        previous_value=prev_value,
        updated_by="admin",
        updated_at=config.updated_at.isoformat(),
        downstream_effects=effects,
    )


@router.get("/decision-weights", tags=["Configuration"],
            summary="Read current decision scoring weights")
async def get_decision_weights(
    repo: BaseConfigRepository = Depends(get_config_repo),
) -> dict:
    """Return current DECISION_WEIGHTS in effect.

    Reads from business_configs DB (Category 3). Falls back to DEFAULT_DECISION_WEIGHTS
    from decision_constants.py if not yet configured in DB.
    Weights must sum to 1.0 — enforced at write time.
    """
    from src.core.constants.decision_constants import DEFAULT_DECISION_WEIGHTS
    cfg = await repo.get_config("DECISION_WEIGHTS")
    weights = cfg.config_value if cfg else DEFAULT_DECISION_WEIGHTS
    return {
        "weights":    weights,
        "source":     "database" if cfg else "defaults",
        "sum_check":  round(sum(weights.values()), 6) if isinstance(weights, dict) else None,
        "effective_in": "immediate" if cfg else "N/A (using compile-time defaults)",
    }
