
"""Bootstrap service — Day-0 initialization orchestrator.

Implements Opti B (Smart Skip) with force_retrain override.

Decision flow per step:
    Step 1: verify_sales_data       — skip if already counted and unchanged
    Step 2: create_minio_buckets    — skip if bucket already exists
    Step 3: backfill_features       — skip if sufficient coverage already exists
    Step 4: train_model             — smart skip logic:
                                       if force_retrain → always train
                                       elif no production model → train
                                       elif features newer than model → train
                                       elif model metrics bad → train
                                       else → skip
    Step 5: mark_system_ready       — always runs, persists final state

State persistence:
    DB: system_bootstrap_status (singleton row system_id='default')
    Redis: key 'bootstrap:status' (cache, no TTL)

Idempotency:
    Each step checks current state before executing.
    Re-running POST /bootstrap/run on a ready system is always safe.
    ON CONFLICT DO UPDATE in backfill ensures no duplicate snapshots.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.constants.feature_constants import MIN_HISTORY_REQUIRED_ROWS
from src.core.constants.model_constants import (
    BASELINE_TEST_MAE_PROMO,
    PROMOTION_THRESHOLD_PCT,
)
from src.core.logging.logger import get_logger

# Bootstrap minimum thresholds
TECHNICAL_MIN_DAYS    = 35    # minimum days for model to train at all (max lag = 35)
RECOMMENDED_MIN_DAYS  = 365   # minimum days for reliable business performance
MAE_VALIDITY_FACTOR   = 1.30  # model metrics bad if mae_promo > baseline × 1.30

StepStatus = Literal["pending", "running", "success", "skipped", "failed"]


@dataclass
class BootstrapStep:
    name      : str
    status    : StepStatus = "pending"
    message   : str        = ""
    detail    : dict       = field(default_factory=dict)


@dataclass
class BootstrapResult:
    task_id       : str
    overall_status: Literal["success", "partial", "failed"]
    is_ready      : bool
    technical_ready: bool
    recommended_ready: bool
    steps         : list[BootstrapStep]
    resume_from   : str | None
    notes         : list[str]
    elapsed_seconds: float

    def last_success_step(self) -> str | None:
        for s in reversed(self.steps):
            if s.status == "success":
                return s.name
        return None

    def to_dict(self) -> dict:
        return {
            "task_id":          self.task_id,
            "overall_status":   self.overall_status,
            "is_ready":         self.is_ready,
            "technical_ready":  self.technical_ready,
            "recommended_ready": self.recommended_ready,
            "resume_from":      self.resume_from,
            "notes":            self.notes,
            "elapsed_seconds":  self.elapsed_seconds,
            "steps": [
                {
                    "name":    s.name,
                    "status":  s.status,
                    "message": s.message,
                    "detail":  s.detail,
                }
                for s in self.steps
            ],
        }


class BootstrapService:
    """Orchestrates Day-0 system initialization.

    Called by bootstrap_task (Celery) which is dispatched by POST /bootstrap/run.
    Updates system_bootstrap_status table after each step for resume capability.
    """

    REDIS_STATUS_KEY = "bootstrap:status"

    def __init__(
        self,
        db_session      : AsyncSession,
        redis_client,
        storage_client,
    ) -> None:
        self._db      = db_session
        self._redis   = redis_client
        self._storage = storage_client
        self._logger  = get_logger(__name__)

    async def execute(
        self,
        task_id      : str,
        force_retrain: bool = False,
    ) -> BootstrapResult:
        t0    = datetime.now(tz=timezone.utc)
        steps = [
            BootstrapStep("verify_sales_data"),
            BootstrapStep("create_minio_buckets"),
            BootstrapStep("backfill_features"),
            BootstrapStep("train_model"),
            BootstrapStep("mark_system_ready"),
        ]
        notes: list[str] = []
        resume_from = None

        self._logger.info(
            "Bootstrap started",
            extra={"task_id": task_id, "force_retrain": force_retrain,
                   "operation": "bootstrap"},
        )

        # ── Step 1: Verify sales data ─────────────────────────────────────────
        s = steps[0]
        s.status = "running"
        await self._persist_step(task_id, s, steps)
        try:
            row_count, date_min, date_max = await self._check_sales_data()
            if row_count == 0:
                s.status  = "failed"
                s.message = "sales_transactions is empty — load data first"
                s.detail  = {"action": "Run: docker compose cp retail_sales.csv postgres:/tmp/ && COPY ..."}
                resume_from = "verify_sales_data"
                notes.append("BLOCKED: Load sales data before running bootstrap.")
                return self._build_result(task_id, steps, notes, resume_from, t0)
            s.status  = "success"
            s.message = f"{row_count:,} rows loaded ({date_min} → {date_max})"
            s.detail  = {"row_count": row_count, "date_min": str(date_min), "date_max": str(date_max)}
            await self._update_status(sales_row_count=row_count)
        except Exception as e:
            s.status  = "failed"
            s.message = str(e)
            resume_from = "verify_sales_data"
            return self._build_result(task_id, steps, notes, resume_from, t0)
        await self._persist_step(task_id, s, steps)

        # ── Step 2: Create MinIO buckets ──────────────────────────────────────
        s = steps[1]
        s.status = "running"
        await self._persist_step(task_id, s, steps)
        try:
            bucket_name = "ml-models"
            created     = self._storage.ensure_bucket(bucket_name)
            s.status    = "success" if created else "skipped"
            s.message   = f"Bucket '{bucket_name}' {'created' if created else 'already exists'}"
            s.detail    = {"bucket": bucket_name, "created": created}
            await self._update_status(minio_bucket_exists=True)
        except Exception as e:
            s.status  = "failed"
            s.message = str(e)
            notes.append(f"WARNING: MinIO bucket setup failed: {e}. Model upload will fail.")
        await self._persist_step(task_id, s, steps)

        # ── Step 3: Backfill features ─────────────────────────────────────────
        s = steps[2]
        s.status = "running"
        await self._persist_step(task_id, s, steps)
        try:
            coverage = await self._check_feature_coverage()
            technical_ready   = coverage["pairs_technical"] >= coverage["n_pairs"] * 0.80
            recommended_ready = coverage["pairs_recommended"] >= coverage["n_pairs"] * 0.80

            if technical_ready and not force_retrain:
                s.status  = "skipped"
                s.message = (
                    f"Feature coverage sufficient: max={coverage['max_days']}d "
                    f"(technical≥{TECHNICAL_MIN_DAYS}, recommended≥{RECOMMENDED_MIN_DAYS})"
                )
                s.detail  = coverage
                if not recommended_ready:
                    notes.append(
                        f"NOTE: technical_ready=true but recommended_ready=false "
                        f"({coverage['pairs_recommended']}/{coverage['n_pairs']} pairs have ≥{RECOMMENDED_MIN_DAYS}d history). "
                        "Model will work but accuracy may be lower than R&D baseline."
                    )
            else:
                need = "insufficient coverage" if not technical_ready else "force_retrain=true"
                self._logger.info(
                    f"Starting backfill ({need})",
                    extra={"task_id": task_id, "coverage": coverage, "operation": "bootstrap"},
                )
                from pipelines.backfill_features_pipeline import run as backfill_run
                backfill_result = await backfill_run(
                    start_date=str(date_min) if date_min else None,
                    end_date=str(date_max) if date_max else None,
                )  # backfill_run accepts ISO strings — convert at boundary
                # Re-check coverage after backfill
                coverage          = await self._check_feature_coverage()
                technical_ready   = coverage["pairs_technical"] >= coverage["n_pairs"] * 0.80
                recommended_ready = coverage["pairs_recommended"] >= coverage["n_pairs"] * 0.80
                s.status  = "success"
                s.message = (
                    f"Backfill complete: {backfill_result['days_processed']} days, "
                    f"{backfill_result['pairs_written']:,} pairs written"
                )
                s.detail  = {**backfill_result, **coverage}

            if not technical_ready:
                s.status  = "failed"
                s.message = (
                    f"Feature coverage still insufficient after backfill "
                    f"({coverage['pairs_technical']}/{coverage['n_pairs']} pairs have ≥{TECHNICAL_MIN_DAYS}d history). "
                    "Ensure sales_transactions has at least 35 days of data."
                )
                resume_from = "backfill_features"
                return self._build_result(task_id, steps, notes, resume_from, t0)

            await self._update_status(
                feature_pairs_covered=coverage.get("n_pairs"),
                feature_days_min=None,  # not tracked — use pairs_technical for readiness
                feature_days_max=coverage.get("max_days"),
                technical_ready=technical_ready,
                recommended_ready=recommended_ready,
            )
        except Exception as e:
            s.status  = "failed"
            s.message = str(e)
            resume_from = "backfill_features"
            return self._build_result(task_id, steps, notes, resume_from, t0)
        await self._persist_step(task_id, s, steps)

        # ── Step 4: Train model (smart skip) ──────────────────────────────────
        s = steps[3]
        s.status = "running"
        await self._persist_step(task_id, s, steps)
        try:
            train_decision, reason = await self._should_train(
                force_retrain=force_retrain,
                latest_snapshot_date=date_max,
            )

            if not train_decision:
                s.status  = "skipped"
                s.message = f"Training skipped: {reason}"
                prod_info = await self._get_production_model_info()
                s.detail  = prod_info
                if prod_info:
                    await self._update_status(
                        production_model_version=prod_info.get("version_id"),
                        model_val_mae_promo=prod_info.get("val_mae_promo"),
                    )
                notes.append(f"Training skipped ({reason}). Use force_retrain=true to override.")
            else:
                self._logger.info(
                    f"Training model ({reason})",
                    extra={"task_id": task_id, "reason": reason, "operation": "bootstrap"},
                )
                from pipelines.training_pipeline import run as train_run
                train_result = await train_run(run_date=str(date_max) if date_max else None)
                if train_result.get("promoted"):
                    s.status  = "success"
                    s.message = (
                        f"Model trained and promoted: {train_result.get('version_tag')} "
                        f"(mae_promo={train_result.get('results', {}).get(0.60, {}).get('mae_promo', '?')})"
                    )
                    s.detail = train_result
                    await self._update_status(
                        production_model_version=train_result.get("version_tag"),
                        model_val_mae_promo=train_result.get("results", {}).get(0.60, {}).get("mae_promo"),
                    )
                else:
                    s.status  = "success"
                    s.message = "Model trained but not promoted (did not beat existing champion)"
                    s.detail  = train_result
                    notes.append(
                        "Trained model did not beat champion threshold — existing model retained. "
                        "This is expected if champion is already good."
                    )
        except Exception as e:
            s.status  = "failed"
            s.message = str(e)
            resume_from = "train_model"
            notes.append(f"Training failed: {e}. System may still work with existing model.")
            # Non-fatal: check if existing production model can cover
            prod_info = await self._get_production_model_info()
            if not prod_info:
                return self._build_result(task_id, steps, notes, resume_from, t0)
            else:
                notes.append("Existing production model found — proceeding despite training failure.")
        await self._persist_step(task_id, s, steps)

        # ── Step 5: Mark system ready ──────────────────────────────────────────
        s = steps[4]
        s.status = "running"
        await self._persist_step(task_id, s, steps)
        try:
            has_model = await self._get_production_model_info()
            coverage  = await self._check_feature_coverage()
            is_ready  = bool(has_model) and coverage.get("pairs_technical", 0) >= coverage.get("n_pairs", 1) * 0.80
            tech_rdy  = coverage.get("pairs_technical", 0) >= coverage.get("n_pairs", 1) * 0.80
            rec_rdy   = coverage.get("pairs_recommended", 0) >= coverage.get("n_pairs", 1) * 0.80

            await self._update_status(
                is_ready=is_ready,
                technical_ready=tech_rdy,
                recommended_ready=rec_rdy,
                last_success_step="mark_system_ready" if is_ready else steps[3].name,
            )
            await self._cache_status_redis(is_ready, tech_rdy, rec_rdy, coverage, has_model)

            s.status  = "success"
            s.message = (
                f"System {'READY' if is_ready else 'NOT READY'} — "
                f"technical_ready={tech_rdy}, recommended_ready={rec_rdy}, "
                f"production_model={'yes' if has_model else 'no'}"
            )
            s.detail  = {
                "is_ready": is_ready,
                "technical_ready": tech_rdy,
                "recommended_ready": rec_rdy,
                "production_model": has_model,
                "feature_coverage": coverage,
            }
        except Exception as e:
            s.status  = "failed"
            s.message = str(e)
        await self._persist_step(task_id, s, steps)

        elapsed = (datetime.now(tz=timezone.utc) - t0).total_seconds()
        self._logger.info(
            "Bootstrap complete",
            extra={
                "task_id": task_id, "elapsed_seconds": round(elapsed, 1),
                "is_ready": s.detail.get("is_ready", False),
                "operation": "bootstrap",
            },
        )
        return self._build_result(task_id, steps, notes, resume_from, t0)

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _check_sales_data(self) -> tuple[int, date, date]:
        result = await self._db.execute(
            text("SELECT COUNT(*), MIN(date), MAX(date) FROM sales_transactions")
        )
        row = result.fetchone()
        return int(row[0] or 0), row[1], row[2]

    async def _check_feature_coverage(self) -> dict:
        result = await self._db.execute(text("""
            SELECT
                COUNT(DISTINCT store_id || '_' || item_id) AS n_pairs,
                MAX(history_days)  AS max_days,
                COUNT(*) FILTER (WHERE history_days >= 35)  AS pairs_technical,
                COUNT(*) FILTER (WHERE history_days >= 365) AS pairs_recommended,
                COUNT(*)           AS total_snapshot_rows
            FROM feature_snapshots
            WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM feature_snapshots)
        """))
        row = result.fetchone()
        return {
            "n_pairs":            int(row[0] or 0),
            "max_days":           int(row[1] or 0),
            "pairs_technical":    int(row[2] or 0),
            "pairs_recommended":  int(row[3] or 0),
            "total_snapshot_rows": int(row[4] or 0),
        }

    async def _get_production_model_info(self) -> dict | None:
        result = await self._db.execute(text("""
            SELECT version_id, version_tag, val_mae_promo, promoted_at, trained_on_date
            FROM   model_registry
            WHERE  is_production = true AND quantile_level = 0.60 AND archived = false
            ORDER  BY promoted_at DESC
            LIMIT  1
        """))
        row = result.fetchone()
        if not row:
            return None
        return {
            "version_id":     row[0],
            "version_tag":    row[1],
            "val_mae_promo":  row[2],
            "promoted_at":    str(row[3]) if row[3] else None,
            "trained_on_date": str(row[4]) if row[4] else None,
        }

    async def _should_train(
        self, force_retrain: bool, latest_snapshot_date: date | None
    ) -> tuple[bool, str]:
        """Returns (should_train, reason_string)."""
        if force_retrain:
            return True, "force_retrain=true"

        prod = await self._get_production_model_info()
        if not prod:
            return True, "no production model exists"

        # Check: are features newer than the trained model?
        if prod.get("trained_on_date") and latest_snapshot_date:
            try:
                trained_on = date.fromisoformat(str(prod["trained_on_date"])[:10])
                snap_date  = (date.fromisoformat(str(latest_snapshot_date)[:10])
                              if not isinstance(latest_snapshot_date, date)
                              else latest_snapshot_date)
                if snap_date > trained_on:
                    return True, f"features newer than model (snapshot={snap_date}, model_trained={trained_on})"
            except (ValueError, TypeError):
                pass  # date parsing failed — skip this check

        # Check: model metrics bad?
        mae_promo = prod.get("val_mae_promo")
        threshold = BASELINE_TEST_MAE_PROMO * MAE_VALIDITY_FACTOR  # 2.641 × 1.30 = 3.43
        if mae_promo and float(mae_promo) > threshold:
            return True, f"model metrics degraded (mae_promo={mae_promo:.4f} > threshold={threshold:.4f})"

        return False, f"production model valid (version={prod['version_id']}, mae_promo={mae_promo})"

    async def _update_status(self, **kwargs) -> None:
        set_clauses = ", ".join(f"{k} = :{k}" for k in kwargs)
        if not set_clauses:
            return
        kwargs["updated_at_val"] = datetime.now(tz=timezone.utc)
        try:
            await self._db.execute(
                text(f"""
                    UPDATE system_bootstrap_status
                    SET {set_clauses}, updated_at = :updated_at_val
                    WHERE system_id = 'default'
                """),
                kwargs,
            )
            await self._db.commit()
        except Exception as e:
            self._logger.warning(f"Bootstrap status persist failed: {e}")
            await self._db.rollback()

    async def _persist_step(self, task_id: str, step: BootstrapStep, all_steps: list) -> None:
        """Persist current step progress. Non-fatal if it fails."""
        try:
            await self._update_status(
                last_success_step=step.name if step.status == "success" else None,
                resume_from=step.name if step.status == "failed" else None,
                notes=step.message,
            )
        except Exception:
            pass

    async def _cache_status_redis(
        self, is_ready, tech_rdy, rec_rdy, coverage, model_info
    ) -> None:
        """Write bootstrap status to Redis for fast health reads."""
        try:
            payload = json.dumps({
                "is_ready":        is_ready,
                "technical_ready": tech_rdy,
                "recommended_ready": rec_rdy,
                "feature_coverage":  coverage,
                "production_model":  model_info,
                "cached_at":         datetime.now(tz=timezone.utc).isoformat(),
            })
            await self._redis.set(self.REDIS_STATUS_KEY, payload)
        except Exception:
            pass  # Redis cache failure is non-fatal

    def _build_result(
        self,
        task_id   : str,
        steps     : list[BootstrapStep],
        notes     : list[str],
        resume_from: str | None,
        t0        : datetime,
    ) -> BootstrapResult:
        succeeded  = [s for s in steps if s.status == "success"]
        failed     = [s for s in steps if s.status == "failed"]
        is_ready   = any(s.name == "mark_system_ready" and s.status == "success" for s in steps)
        tech_rdy   = False
        rec_rdy    = False
        for s in steps:
            if s.detail.get("technical_ready"):
                tech_rdy = True
            if s.detail.get("recommended_ready"):
                rec_rdy = True

        if failed:
            overall = "failed" if not succeeded else "partial"
        else:
            overall = "success"

        return BootstrapResult(
            task_id=task_id,
            overall_status=overall,
            is_ready=is_ready,
            technical_ready=tech_rdy,
            recommended_ready=rec_rdy,
            steps=steps,
            resume_from=resume_from,
            notes=notes,
            elapsed_seconds=round((datetime.now(tz=timezone.utc) - t0).total_seconds(), 1),
        )