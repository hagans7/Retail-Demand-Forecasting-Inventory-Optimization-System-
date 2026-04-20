
"""Feature engineering pipeline — daily 01:00.

Computes all 25 P1 features from sales_transactions and writes to feature_snapshots.
Triggered by data_quality_gate_pipeline after CRITICAL checks pass.

Algorithm (vectorized — no per-pair loops):
    1. Load last 35 days of sales (max lag=28 + 7-day buffer)
    2. Sort by (store_id, item_id, date)
    3. Lag features: groupby(pair).shift(k) — never future-leaking
    4. Rolling: shift(1) BEFORE rolling window (leakage guard)
    5. Cyclic calendar features (sin/cos encoding)
    6. Promo streak and days_since_last_promo
    7. Upsert today's snapshot rows to feature_snapshots

"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import text

from src.core.constants.feature_constants import DROPPED_FEATURES, ALL_P1_FEATURES
from src.core.logging.logger import get_logger

_logger = get_logger(__name__)


async def run(run_date: str | None = None) -> dict:
    today = date.fromisoformat(run_date) if run_date else date.today()
    t0    = datetime.now(tz=timezone.utc)

    _logger.info(
        "Feature engineering pipeline started",
        extra={"run_date": str(today), "pipeline_name": "feature_engineering"},
    )

    from src.providers.infrastructure import make_worker_session

    # ── 1. Load 35-day sales window ───────────────────────────────────────
    start = today - timedelta(days=35)
    async with make_worker_session() as db:
        result = await db.execute(
            text("""
                SELECT store_id, item_id, date, sales, price, promo
                FROM   sales_transactions
                WHERE  date BETWEEN :start AND :today
                ORDER  BY store_id, item_id, date
            """),
            {"start": start, "today": today},  # date objects
        )
        rows = result.fetchall()
        keys = result.keys()

    if not rows:
        _logger.warning("Feature engineering: no sales data",
                        extra={"pipeline_name": "feature_engineering"})
        return {"status": "no_data", "rows_written": 0}

    df = pd.DataFrame(rows, columns=list(keys))
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["store_id", "item_id", "date"]).reset_index(drop=True)

    grp = df.groupby(["store_id", "item_id"])["sales"]

    # ── 2. Lag features ────────────────────────────────────────────────────
    for lag in [7, 14, 21, 28, 35]:
        df[f"lag_{lag}"] = grp.transform(lambda x: x.shift(lag))

    # ── 3. Rolling stats — shift(1) first (leakage guard) ─────────────────
    for w in [7, 14, 28]:
        df[f"rolling_mean_{w}"] = grp.transform(
            lambda x, w=w: x.shift(1).rolling(w, min_periods=1).mean()
        )
    for w in [7, 14]:
        df[f"rolling_std_{w}"] = grp.transform(
            lambda x, w=w: x.shift(1).rolling(w, min_periods=2).std().fillna(0)
        )
        df[f"rolling_cv_{w}"] = (
            df[f"rolling_std_{w}"] / df[f"rolling_mean_{w}"].replace(0, np.nan)
        ).fillna(0)

    # ── 4. Weekday one-hot ─────────────────────────────────────────────────
    df["_wd"] = df["date"].dt.weekday
    for d in range(7):
        df[f"wd_{d}"] = (df["_wd"] == d).astype("int8")

    # ── 5. Cyclic calendar ─────────────────────────────────────────────────
    doy   = df["date"].dt.dayofyear
    month = df["date"].dt.month
    df["month_sin"]     = np.sin(2 * np.pi * month / 12)
    df["month_cos"]     = np.cos(2 * np.pi * month / 12)
    df["doy_sin"]       = np.sin(2 * np.pi * doy / 365)
    df["doy_cos"]       = np.cos(2 * np.pi * doy / 365)
    df["week_of_month"] = (df["date"].dt.day - 1) // 7 + 1

    # ── 6. Promo streak and recovery ───────────────────────────────────────
    def _streak(s: pd.Series) -> pd.Series:
        return s * (s.groupby((s != s.shift()).cumsum()).cumcount() + 1)

    def _days_since(s: pd.Series) -> pd.Series:
        return (s == 0).groupby((s != s.shift()).cumsum()).cumcount().where(s == 0, 0)

    df["promo_streak_day"]       = grp.transform(lambda x: _streak(x) if "promo" in df.columns else pd.Series(0, index=x.index)) if "promo" in df.columns else 0
    pgrp = df.groupby(["store_id","item_id"])["promo"]
    df["promo_streak_day"]       = pgrp.transform(_streak)
    df["days_since_last_promo"]  = pgrp.transform(_days_since)

    # ── 7. History days ────────────────────────────────────────────────────
    df["history_days"] = df.groupby(["store_id","item_id"]).cumcount() + 1

    # ── 8. Drop non-P1 lags ────────────────────────────────────────────────
    df = df.drop(columns=[c for c in DROPPED_FEATURES if c in df.columns], errors="ignore")
    df = df.drop(columns=["_wd"], errors="ignore")

    # ── 9. Filter to today only and upsert ────────────────────────────────
    today_df = df[df["date"].dt.date == today].copy()
    if today_df.empty:
        _logger.warning("Feature engineering: no rows for today",
                        extra={"pipeline_name": "feature_engineering"})
        return {"status": "no_today_rows", "rows_written": 0}

    p1_cols = ALL_P1_FEATURES  # 25 features

    async with make_worker_session() as db:
        rows_written = 0
        for _, row in today_df.iterrows():
            vals: dict = {
                "store_id":      str(row["store_id"]),
                "item_id":       str(row["item_id"]),
                "snapshot_date": today,  # date object
                "history_days":  int(row.get("history_days", 0)),
            }
            for col in p1_cols:
                v = row.get(col, np.nan)
                vals[col] = None if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v)

            await db.execute(
                text("""
                    INSERT INTO feature_snapshots
                        (store_id, item_id, snapshot_date, history_days,
                         lag_7, lag_14, lag_21,
                         rolling_mean_7, rolling_mean_14, rolling_mean_28,
                         rolling_std_7, rolling_std_14, rolling_cv_7, rolling_cv_14,
                         wd_0, wd_1, wd_2, wd_3, wd_4, wd_5, wd_6,
                         month_sin, month_cos, doy_sin, doy_cos, week_of_month,
                         promo, promo_streak_day, days_since_last_promo)
                    VALUES
                        (:store_id, :item_id, :snapshot_date, :history_days,
                         :lag_7, :lag_14, :lag_21,
                         :rolling_mean_7, :rolling_mean_14, :rolling_mean_28,
                         :rolling_std_7, :rolling_std_14, :rolling_cv_7, :rolling_cv_14,
                         :wd_0, :wd_1, :wd_2, :wd_3, :wd_4, :wd_5, :wd_6,
                         :month_sin, :month_cos, :doy_sin, :doy_cos, :week_of_month,
                         :promo, :promo_streak_day, :days_since_last_promo)
                    ON CONFLICT (store_id, item_id, snapshot_date) DO UPDATE SET
                        lag_7              = EXCLUDED.lag_7,
                        lag_14             = EXCLUDED.lag_14,
                        lag_21             = EXCLUDED.lag_21,
                        rolling_mean_7     = EXCLUDED.rolling_mean_7,
                        rolling_mean_14    = EXCLUDED.rolling_mean_14,
                        rolling_mean_28    = EXCLUDED.rolling_mean_28,
                        rolling_std_7      = EXCLUDED.rolling_std_7,
                        rolling_std_14     = EXCLUDED.rolling_std_14,
                        rolling_cv_7       = EXCLUDED.rolling_cv_7,
                        rolling_cv_14      = EXCLUDED.rolling_cv_14,
                        wd_0=EXCLUDED.wd_0, wd_1=EXCLUDED.wd_1, wd_2=EXCLUDED.wd_2,
                        wd_3=EXCLUDED.wd_3, wd_4=EXCLUDED.wd_4, wd_5=EXCLUDED.wd_5,
                        wd_6=EXCLUDED.wd_6,
                        month_sin=EXCLUDED.month_sin, month_cos=EXCLUDED.month_cos,
                        doy_sin=EXCLUDED.doy_sin,     doy_cos=EXCLUDED.doy_cos,
                        week_of_month=EXCLUDED.week_of_month,
                        promo=EXCLUDED.promo,
                        promo_streak_day=EXCLUDED.promo_streak_day,
                        days_since_last_promo=EXCLUDED.days_since_last_promo,
                        history_days=EXCLUDED.history_days
                """),
                vals,
            )
            rows_written += 1
        await db.commit()

    elapsed = round((datetime.now(tz=timezone.utc) - t0).total_seconds(), 1)
    _logger.info(
        "Feature engineering pipeline complete",
        extra={"rows_written": rows_written, "elapsed_seconds": elapsed,
               "pipeline_name": "feature_engineering"},
    )
    return {"status": "ok", "rows_written": rows_written}


if __name__ == "__main__":
    asyncio.run(run())