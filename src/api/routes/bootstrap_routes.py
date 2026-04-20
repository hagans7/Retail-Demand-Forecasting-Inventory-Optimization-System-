

"""Bootstrap routes — Day-0 initialization endpoints.

POST /bootstrap/run          Dispatch bootstrap Celery task (async)
GET  /bootstrap/status       Current bootstrap progress / final state
GET  /health/readiness       Structured readiness checklist with next_action
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.core.logging.logger import get_logger

router  = APIRouter(tags=["Bootstrap"])
_logger = get_logger(__name__)


# ── Request/Response schemas ───────────────────────────────────────────────────

class BootstrapRunRequest(BaseModel):
    """Bootstrap run request.

    force_retrain:
        false (default) — Smart Skip: skip training if production model valid.
        true            — Force Retrain: always retrain even if model exists.
                          Use for incident recovery, benchmarking, or explicit rebuild.
    """
    force_retrain: bool = False
    reason       : str  = "Initial bootstrap"


class StepOut(BaseModel):
    name   : str
    status : str
    message: str
    detail : dict = {}


class BootstrapRunResponse(BaseModel):
    task_id: str
    status : str
    message: str
    poll_url: str


class BootstrapStatusResponse(BaseModel):
    task_id         : str | None
    overall_status  : str
    is_ready        : bool
    technical_ready : bool
    recommended_ready: bool
    resume_from     : str | None
    notes           : list[str]
    steps           : list[StepOut]
    elapsed_seconds : float | None


class ReadinessItem(BaseModel):
    ok          : bool
    value       : str
    action      : str | None = None


class ReadinessResponse(BaseModel):
    """Structured readiness checklist.

    overall_ready = True only when ALL critical checks pass.
    technical_ready = True means training can run (≥35 days history).
    recommended_ready = True means model reliability matches R&D baseline (≥365 days).
    next_action is the single most important step the operator should take.
    """
    overall_ready   : bool
    technical_ready : bool
    recommended_ready: bool
    next_action     : str
    checklist       : dict[str, ReadinessItem]


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/bootstrap/run",
    response_model=BootstrapRunResponse,
    summary="Trigger Day-0 bootstrap initialization (async)",
)
async def run_bootstrap(request: BootstrapRunRequest) -> BootstrapRunResponse:
    """Dispatch the bootstrap Celery task.

    Idempotent: safe to call multiple times. Smart skip prevents unnecessary work.

    Bootstrap steps (sequential):
        1. verify_sales_data    — check sales_transactions has data
        2. create_minio_buckets — ensure ml-models bucket exists
        3. backfill_features    — compute 25 features for all historical dates
        4. train_model          — train LightGBM (smart skip if model already valid)
        5. mark_system_ready    — persist final state to DB + Redis

    Backfill for 4 years × 2500 pairs takes 15–60 minutes.
    Poll GET /bootstrap/status for progress.

    force_retrain=true forces Step 4 even if production model is valid.
    Use only for: debug, incident recovery, explicit benchmark rebuild.
    """
    try:
        from src.worker import bootstrap_task
        result = bootstrap_task.delay(force_retrain=request.force_retrain)
        _logger.info(
            "Bootstrap dispatched",
            extra={"task_id": result.id, "force_retrain": request.force_retrain,
                   "reason": request.reason, "operation": "bootstrap_run"},
        )
        return BootstrapRunResponse(
            task_id=result.id,
            status="dispatched",
            message=(
                "Bootstrap task dispatched. "
                "Backfill takes 15-60 minutes for full 4-year history. "
                f"Poll GET /bootstrap/status?task_id={result.id} for progress."
            ),
            poll_url=f"/bootstrap/status?task_id={result.id}",
        )
    except Exception as e:
        _logger.error("Bootstrap dispatch failed", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=f"Could not dispatch bootstrap task: {e}. Is Celery worker running?",
        )


@router.get(
    "/bootstrap/status",
    response_model=BootstrapStatusResponse,
    summary="Bootstrap progress and current system state",
)
async def get_bootstrap_status(
    task_id: str | None = Query(None, description="Celery task ID from POST /bootstrap/run"),
) -> BootstrapStatusResponse:
    """Return current bootstrap state.

    If task_id provided: returns live Celery task progress.
    Always returns persisted DB state (survives container restart).

    status values:
        PENDING   — task queued, not started
        STARTED   — task running
        SUCCESS   — task completed (check is_ready for system state)
        FAILURE   — task failed (check resume_from for where to restart)
    """
    from src.providers.infrastructure import _session_factory
    from sqlalchemy import text

    # ── Read persisted state from DB ──────────────────────────────────────────
    db_state = {
        "overall_status":   "unknown",
        "is_ready":         False,
        "technical_ready":  False,
        "recommended_ready": False,
        "last_success_step": None,
        "resume_from":      None,
        "notes":            None,
    }
    try:
        async with _session_factory() as db:
            result = await db.execute(text("""
                SELECT is_ready, technical_ready, recommended_ready,
                       last_success_step, resume_from, notes,
                       sales_row_count, feature_pairs_covered, feature_days_min,
                       feature_days_max, production_model_version, model_val_mae_promo,
                       minio_bucket_exists, last_backfill_date, last_run_at
                FROM system_bootstrap_status WHERE system_id = 'default'
            """))
            row = result.fetchone()
            if row:
                db_state.update({
                    "is_ready":          bool(row[0]),
                    "technical_ready":   bool(row[1]),
                    "recommended_ready": bool(row[2]),
                    "last_success_step": row[3],
                    "resume_from":       row[4],
                    "notes":             row[5],
                    "sales_row_count":   row[6],
                    "feature_pairs_covered": row[7],
                    "feature_days_min":  row[8],
                    "feature_days_max":  row[9],
                    "production_model":  row[10],
                    "model_val_mae_promo": row[11],
                    "minio_bucket_exists": bool(row[12]) if row[12] is not None else False,
                    "last_backfill_date": row[13],
                    "last_run_at":       str(row[14]) if row[14] else None,
                })
    except Exception as e:
        _logger.warning(f"Could not read bootstrap status from DB: {e}")

    # ── Determine overall status from Celery if task_id provided ─────────────
    celery_status = "UNKNOWN"
    celery_result = None
    elapsed = None
    if task_id:
        try:
            from src.worker import app as celery_app
            task = celery_app.AsyncResult(task_id)
            celery_status = task.status
            if task.ready() and task.result:
                celery_result = task.result if not isinstance(task.result, Exception) else None
        except Exception:
            celery_status = "UNAVAILABLE"

    # ── Build step summary from DB state ─────────────────────────────────────
    steps_out = []
    if celery_result and isinstance(celery_result, dict) and "steps" in celery_result:
        steps_out = [
            StepOut(
                name=s["name"], status=s["status"],
                message=s["message"], detail=s.get("detail", {}),
            )
            for s in celery_result["steps"]
        ]
    else:
        # Reconstruct from DB persisted state
        step_defs = [
            ("verify_sales_data",    db_state.get("sales_row_count", 0) not in (None, 0)),
            ("create_minio_buckets", db_state.get("minio_bucket_exists", False)),
            ("backfill_features",    (db_state.get("feature_days_min") or 0) >= 35),
            ("train_model",          db_state.get("production_model") is not None),
            ("mark_system_ready",    db_state.get("is_ready", False)),
        ]
        for name, done in step_defs:
            if done:
                status = "success"
                msg    = "completed"
            elif name == db_state.get("resume_from"):
                status = "failed"
                msg    = db_state.get("notes") or "failed"
            else:
                status = "pending"
                msg    = "not started"
            steps_out.append(StepOut(name=name, status=status, message=msg))

    overall = "not_started"
    if db_state["is_ready"]:
        overall = "success"
    elif db_state["resume_from"]:
        overall = "partial"
    elif celery_status == "STARTED":
        overall = "running"

    notes_list = [db_state["notes"]] if db_state.get("notes") else []
    if not db_state["is_ready"] and celery_status not in ("STARTED", "PENDING"):
        notes_list.append("System not ready. Run POST /bootstrap/run to initialize.")

    return BootstrapStatusResponse(
        task_id=task_id,
        overall_status=overall,
        is_ready=db_state["is_ready"],
        technical_ready=db_state["technical_ready"],
        recommended_ready=db_state["recommended_ready"],
        resume_from=db_state.get("resume_from"),
        notes=notes_list,
        steps=steps_out,
        elapsed_seconds=elapsed,
    )


@router.get(
    "/health/readiness",
    response_model=ReadinessResponse,
    summary="Structured readiness checklist with actionable next steps",
)
async def get_readiness() -> ReadinessResponse:
    """Detailed system readiness checklist.

    Checks:
        sales_data_loaded       — sales_transactions has rows
        minio_bucket_exists     — ml-models bucket accessible
        feature_snapshots_ready — technical (≥35d) and recommended (≥365d)
        production_model_exists — is_production=true in model_registry
        model_artifact_accessible — MinIO object readable

    technical_ready = training can run (≥35 days history per pair)
    recommended_ready = model accuracy expected to match R&D baseline (≥365 days)

    next_action is the single most important operator action right now.
    """
    from src.providers.infrastructure import _session_factory, get_storage_client
    from sqlalchemy import text

    checklist: dict[str, ReadinessItem] = {}
    async with _session_factory() as db:

        # Sales data
        try:
            r = await db.execute(text("SELECT COUNT(*), MIN(date), MAX(date) FROM sales_transactions"))
            row = r.fetchone()
            count = int(row[0] or 0)
            checklist["sales_data_loaded"] = ReadinessItem(
                ok=count > 0,
                value=f"{count:,} rows ({row[1]} → {row[2]})" if count > 0 else "0 rows",
                action=None if count > 0 else (
                    "docker compose cp retail_sales.csv postgres:/tmp/ && "
                    "docker compose exec postgres psql ... COPY sales_transactions..."
                ),
            )
        except Exception as e:
            checklist["sales_data_loaded"] = ReadinessItem(ok=False, value=str(e),
                                                            action="Check database connectivity")

        # Feature snapshots
        try:
            # Correct approach: check how many pairs have ENOUGH history
            # MIN(history_days) is always 1 (the very first day of data) — not useful
            # Instead: count pairs where MAX snapshot history_days >= threshold
            r = await db.execute(text("""
                SELECT
                    COUNT(DISTINCT store_id || '_' || item_id)              AS n_pairs,
                    MAX(history_days)                                       AS max_days,
                    COUNT(*) FILTER (WHERE history_days >= 35)             AS pairs_technical,
                    COUNT(*) FILTER (WHERE history_days >= 365)            AS pairs_recommended
                FROM feature_snapshots
                WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM feature_snapshots)
            """))
            row = r.fetchone()
            n_pairs           = int(row[0] or 0)
            max_days          = int(row[1] or 0)
            pairs_technical   = int(row[2] or 0)
            pairs_recommended = int(row[3] or 0)
            # Ready when ≥80% of all pairs have sufficient history
            threshold_n = max(1, int(n_pairs * 0.80))
            tech_rdy    = pairs_technical   >= threshold_n
            rec_rdy     = pairs_recommended >= threshold_n
            checklist["feature_snapshots_technical"] = ReadinessItem(
                ok=tech_rdy,
                value=(f"{pairs_technical}/{n_pairs} pairs have ≥35d history "
                       f"(max_days={max_days}, need ≥80% of pairs)"),
                action=None if tech_rdy else "POST /bootstrap/run to backfill features",
            )
            checklist["feature_snapshots_recommended"] = ReadinessItem(
                ok=rec_rdy,
                value=(f"{pairs_recommended}/{n_pairs} pairs have ≥365d history "
                       f"(recommended for R&D baseline accuracy)"),
                action=None if rec_rdy else (
                    "POST /bootstrap/run (backfill will use all available sales history)"
                ),
            )
        except Exception as e:
            checklist["feature_snapshots_technical"]   = ReadinessItem(ok=False, value=str(e))
            checklist["feature_snapshots_recommended"] = ReadinessItem(ok=False, value=str(e))
            tech_rdy = rec_rdy = False

        # Production model
        try:
            r = await db.execute(text("""
                SELECT version_id, val_mae_promo, promoted_at
                FROM model_registry
                WHERE is_production=true AND quantile_level=0.60 AND archived=false
                ORDER BY promoted_at DESC LIMIT 1
            """))
            row = r.fetchone()
            has_model = row is not None
            checklist["production_model_exists"] = ReadinessItem(
                ok=has_model,
                value=(f"{row[0]} (mae_promo={row[1]:.4f}, promoted={str(row[2])[:10]})"
                       if has_model else "none"),
                action=None if has_model else "POST /bootstrap/run (will train and promote model)",
            )
        except Exception as e:
            checklist["production_model_exists"] = ReadinessItem(ok=False, value=str(e))
            has_model = False

        # MinIO bucket
        try:
            storage = get_storage_client()
            bucket_ok = storage.bucket_exists("ml-models")
            checklist["minio_bucket_exists"] = ReadinessItem(
                ok=bucket_ok,
                value="ml-models bucket accessible" if bucket_ok else "ml-models bucket missing",
                action=None if bucket_ok else "POST /bootstrap/run (will create bucket)",
            )
        except Exception as e:
            checklist["minio_bucket_exists"] = ReadinessItem(ok=False, value=str(e),
                                                              action="Check MinIO service")
            bucket_ok = False

    # Determine overall readiness and next_action
    overall_ready = (
        checklist["sales_data_loaded"].ok
        and checklist["feature_snapshots_technical"].ok
        and checklist["production_model_exists"].ok
        and checklist["minio_bucket_exists"].ok
    )

    if not checklist["sales_data_loaded"].ok:
        next_action = "STEP 1: Load sales data — see README Step 6.1"
    elif not checklist.get("feature_snapshots_technical", ReadinessItem(ok=True, value="")).ok:
        next_action = "STEP 2: POST /bootstrap/run — will backfill 25 features for all historical dates"
    elif not checklist["production_model_exists"].ok:
        next_action = "STEP 3: POST /bootstrap/run — will train and promote LightGBM model"
    elif not checklist["minio_bucket_exists"].ok:
        next_action = "STEP 4: POST /bootstrap/run — will create MinIO bucket"
    elif not checklist["feature_snapshots_recommended"].ok:
        next_action = (
            "System is TECHNICALLY READY but has less than 365 days history. "
            "Accuracy may be lower than R&D baseline (MAE_promo 2.641). "
            "All forecast endpoints are available."
        )
    else:
        next_action = "System FULLY READY — all endpoints available"

    return ReadinessResponse(
        overall_ready=overall_ready,
        technical_ready=tech_rdy,
        recommended_ready=rec_rdy,
        next_action=next_action,
        checklist=checklist,
    )