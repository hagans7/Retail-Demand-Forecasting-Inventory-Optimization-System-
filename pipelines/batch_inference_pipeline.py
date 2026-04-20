

"""Batch inference pipeline — daily 02:00.

Runs daily forecast for ALL 2500 pairs in a single vectorized predict() call.
Writing to forecast_results and computing replenishment signals.

Algorithm:
    1. Load all feature rows for today from feature_snapshots (single query)
    2. Load production model (q60) — singleton cached in worker
    3. Single vectorized predict(X_all) — do NOT loop per pair
    4. Clip predictions >= 0
    5. Apply safety factor per pair (cold_start vs normal vs promo)
    6. Bulk INSERT to forecast_results
    7. Trigger forecast_evaluation for yesterday
"""
from __future__ import annotations

import asyncio
import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import text

from src.core.constants.business_constants import (
    SAFETY_FACTOR_COLD_START,
    SAFETY_FACTOR_NORMAL,
    SAFETY_FACTOR_PROMO,
    STOCKOUT_CRITICAL_DAYS,
    STOCKOUT_HIGH_DAYS,
    STOCKOUT_MEDIUM_DAYS,
)
from src.core.constants.feature_constants import INFERENCE_FEATURES
from src.core.constants.model_constants import BEST_ITERATION_PRODUCTION
from src.core.logging.logger import get_logger

_logger = get_logger(__name__)


async def run(run_date: str | None = None) -> dict:
    today = date.fromisoformat(run_date) if run_date else date.today()
    t0    = datetime.now(tz=timezone.utc)

    _logger.info("Batch inference pipeline started",
                 extra={"run_date": str(today), "pipeline_name": "batch_inference"})

    from src.providers.infrastructure import make_worker_session, get_model_client, get_storage_client
    from src.repositories.model_registry_repository import ModelRegistryRepository

    # ── 1. Load all feature snapshots for today ───────────────────────────
    async with make_worker_session() as db:
        result = await db.execute(
            text("""
                SELECT store_id, item_id, history_days, promo,
                       lag_7, lag_14, lag_21,
                       rolling_mean_7, rolling_mean_14, rolling_mean_28,
                       rolling_std_7, rolling_std_14, rolling_cv_7, rolling_cv_14,
                       wd_0, wd_1, wd_2, wd_3, wd_4, wd_5, wd_6,
                       month_sin, month_cos, doy_sin, doy_cos, week_of_month,
                       promo_streak_day, days_since_last_promo
                FROM   feature_snapshots
                WHERE  snapshot_date = :today
            """),
            {"today": today},  # date object
        )
        rows = result.fetchall()
        col_keys = list(result.keys())

        if not rows:
            _logger.warning("Batch inference: no feature snapshots for today",
                            extra={"pipeline_name": "batch_inference"})
            return {"status": "no_features", "pairs_processed": 0}

        # ── 2. Load production model ──────────────────────────────────────
        registry = ModelRegistryRepository(db)
        try:
            prod_model = await registry.get_production_model()
        except Exception as e:
            _logger.error(f"No production model: {e}",
                          extra={"pipeline_name": "batch_inference"})
            return {"status": "no_model", "pairs_processed": 0}

    df = pd.DataFrame(rows, columns=col_keys)
    store_ids    = df["store_id"].values
    item_ids     = df["item_id"].values
    history_days = df["history_days"].fillna(0).values
    promo_flags  = df["promo"].fillna(0).values

    # ── 3. Build feature matrix ───────────────────────────────────────────
    X = df.reindex(columns=INFERENCE_FEATURES, fill_value=0.0).fillna(0.0).astype("float32")

    # ── 4. Single vectorized predict ──────────────────────────────────────
    storage = get_storage_client()
    model   = get_model_client()
    model.load_model(prod_model.version_id, quantile_level=0.60)
    raw_preds = model.predict(X, num_iteration=BEST_ITERATION_PRODUCTION)
    preds     = np.clip(raw_preds, 0.0, None)

    # ── 5. Safety factors and stockout risk ───────────────────────────────
    from src.core.constants.business_constants import COLD_START_TIER1_DAYS, MIN_HISTORY_REQUIRED_ROWS

    def safety(h: int, has_promo: int) -> float:
        if h < COLD_START_TIER1_DAYS:
            return SAFETY_FACTOR_COLD_START
        if h < MIN_HISTORY_REQUIRED_ROWS:
            return SAFETY_FACTOR_COLD_START
        return SAFETY_FACTOR_PROMO if has_promo else SAFETY_FACTOR_NORMAL

    def stockout_risk(pred: float) -> str:
        dpc = pred / 7  # daily avg
        if dpc < STOCKOUT_CRITICAL_DAYS: return "CRITICAL"
        if dpc < STOCKOUT_HIGH_DAYS:     return "HIGH"
        if dpc < STOCKOUT_MEDIUM_DAYS:   return "MEDIUM"
        return "LOW"

    import uuid
    # ── 6. Bulk insert ────────────────────────────────────────────────────
    async with make_worker_session() as db:
        forecast_date_7d = [(today + timedelta(days=i)) for i in range(7)]
        inserted = 0
        for i in range(len(store_ids)):
            sf   = safety(int(history_days[i]), int(promo_flags[i]))
            pred = float(preds[i])
            tier = ("TIER1_PROXY" if history_days[i] < COLD_START_TIER1_DAYS
                    else "TIER2_REDUCED" if history_days[i] < MIN_HISTORY_REQUIRED_ROWS
                    else "NONE")
            # Write one row per pair (daily aggregate forecast)
            await db.execute(
                text("""
                    INSERT INTO forecast_results
                        (forecast_id, store_id, item_id, forecast_date,
                         predicted_sales, lower_bound, upper_bound,
                         model_version, quantile_level, stockout_risk,
                         safety_factor, cold_start_tier)
                    VALUES
                        (:fid, :sid, :iid, :fdate,
                         :pred, :lo, :hi,
                         :mv, 0.60, :risk, :sf, :tier)
                    ON CONFLICT DO NOTHING
                """),
                {
                    "fid":   str(uuid.uuid4()),
                    "sid":   str(store_ids[i]),
                    "iid":   str(item_ids[i]),
                    "fdate": today,  # date object
                    "pred":  round(pred, 2),
                    "lo":    round(pred * 0.85, 2),
                    "hi":    round(pred * 1.20, 2),
                    "mv":    prod_model.version_id,
                    "risk":  stockout_risk(pred),
                    "sf":    sf,
                    "tier":  tier,
                },
            )
            inserted += 1
        await db.commit()

    elapsed = round((datetime.now(tz=timezone.utc) - t0).total_seconds(), 1)
    _logger.info(
        "Batch inference pipeline complete",
        extra={"pairs_processed": inserted, "elapsed_seconds": elapsed,
               "pipeline_name": "batch_inference"},
    )
    return {"status": "ok", "pairs_processed": inserted}


if __name__ == "__main__":
    asyncio.run(run())