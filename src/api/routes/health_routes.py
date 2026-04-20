"""Health endpoint — full V1 + V2 metrics.

GET /health         Full system health (V1 model + V2 simulation drift)
                    Also shows bootstrap readiness summary.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    status                            : str   = "ok"
    # Bootstrap / readiness
    system_ready                      : bool  = False
    technical_ready                   : bool  = False
    recommended_ready                 : bool  = False
    next_action                       : str   = "GET /health/readiness for detailed checklist"
    # V1 model health
    model_version                     : str   = ""
    rolling_7d_mae_promo              : float | None = None
    rolling_28d_mae_promo             : float | None = None
    baseline_mae_promo                : float = 2.641
    retraining_recommended            : bool  = False
    # V2 decision drift metrics
    decision_approval_success_rate_7d : float | None = None
    roi_prediction_bias_7d            : float | None = None
    override_rate_7d                  : float | None = None
    simulation_count_7d               : int = 0


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Full system health check.

    system_ready = True only when features + model + MinIO all ready.
    next_action gives the single most important operator step when not ready.

    Use GET /health/readiness for the full structured checklist.
    Use GET /bootstrap/status for bootstrap pipeline progress.
    """
    health_data: dict = {"status": "ok", "baseline_mae_promo": 2.641}

    # ── Bootstrap / readiness (fast path from Redis cache) ────────────────────
    try:
        import json
        import redis.asyncio as aioredis
        r = aioredis.from_url("redis://redis:6379/0", decode_responses=True)
        cached = await r.get("bootstrap:status")
        if cached:
            bs = json.loads(cached)
            health_data["system_ready"]       = bs.get("is_ready", False)
            health_data["technical_ready"]    = bs.get("technical_ready", False)
            health_data["recommended_ready"]  = bs.get("recommended_ready", False)
            health_data["next_action"] = (
                "System READY — all endpoints available"
                if bs.get("is_ready")
                else "POST /bootstrap/run to initialize system"
            )
        else:
            # No cached state — check DB directly
            from src.providers.infrastructure import _session_factory
            from sqlalchemy import text
            async with _session_factory() as db:
                res = await db.execute(text(
                    "SELECT is_ready, technical_ready, recommended_ready "
                    "FROM system_bootstrap_status WHERE system_id='default'"
                ))
                row = res.fetchone()
                if row:
                    health_data["system_ready"]      = bool(row[0])
                    health_data["technical_ready"]   = bool(row[1])
                    health_data["recommended_ready"] = bool(row[2])
                health_data["next_action"] = (
                    "System READY" if health_data.get("system_ready")
                    else "POST /bootstrap/run to initialize. See GET /health/readiness for checklist."
                )
    except Exception:
        health_data["next_action"] = "GET /health/readiness for detailed status"

    # ── V1 model health ───────────────────────────────────────────────────────
    try:
        from src.providers.infrastructure import _session_factory
        from src.repositories.model_registry_repository import ModelRegistryRepository
        from src.repositories.monitoring_repository import MonitoringRepository
        from src.services.monitor_model_health import MonitorModelHealthService

        async with _session_factory() as db:
            svc    = MonitorModelHealthService(
                MonitoringRepository(db), ModelRegistryRepository(db)
            )
            h_data = await svc.execute()
            health_data.update(h_data)
    except Exception:
        pass  # degrade gracefully — no model yet on fresh install

    # ── V2 simulation drift ───────────────────────────────────────────────────
    try:
        from src.providers.infrastructure import _session_factory
        from src.repositories.decision_repository import DecisionRepository

        async with _session_factory() as db:
            drift = await DecisionRepository(db).get_simulation_drift_metrics(lookback_days=7)
            health_data.update({
                "simulation_count_7d":              drift.get("n_simulations", 0),
                "override_rate_7d":                 drift.get("override_rate"),
                "decision_approval_success_rate_7d": drift.get("approval_success_rate"),
                "roi_prediction_bias_7d":            drift.get("roi_prediction_bias"),
            })
    except Exception:
        pass

    return HealthResponse(**health_data)
