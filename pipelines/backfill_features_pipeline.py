
"""Historical feature backfill pipeline — Day-0 bootstrap only.

ARCHITECTURE: batch-per-30-days instead of row-per-day.
Processes 30 days at a time, builds ALL feature rows in pandas,
then inserts with a single bulk executemany() call per batch.

"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import text

from src.core.constants.feature_constants import ALL_P1_FEATURES, DROPPED_FEATURES
from src.core.logging.logger import get_logger

_logger = get_logger(__name__)

# Process 30 days per batch — balances memory vs round-trip count
_BATCH_DAYS = 30
# Window needed before first target date (max lag=35 + buffer)
_WINDOW_BEFORE = 35


async def run(
    start_date: str | None = None,
    end_date:   str | None = None,
) -> dict:
    """Run historical backfill from start_date to end_date (inclusive).

    Auto-resumes from last completed snapshot_date if partial run exists.

    Args:
        start_date: ISO date. Default: day after MAX(snapshot_date) in DB,
                    or MIN(date) from sales_transactions if snapshots empty.
        end_date:   ISO date. Default: MAX(date) from sales_transactions.

    Returns:
        dict: status, days_processed, pairs_written, skipped_days, elapsed_seconds
    """
    from src.providers.infrastructure import make_worker_session

    t0 = datetime.now(tz=timezone.utc)
    _logger.info("Backfill pipeline started",
                 extra={"start_date": start_date, "end_date": end_date,
                        "pipeline_name": "backfill_features"})

    # ── Determine date range ──────────────────────────────────────────────────
    async with make_worker_session() as db:
        r = await db.execute(text(
            "SELECT MIN(date), MAX(date) FROM sales_transactions"
        ))
        row = r.fetchone()
        if not row or row[0] is None:
            _logger.error("No sales data — cannot backfill")
            return {"status": "no_sales_data", "days_processed": 0,
                    "pairs_written": 0, "skipped_days": 0, "elapsed_seconds": 0}
        db_min, db_max = row[0], row[1]

        # Auto-resume: start from day after last completed snapshot
        if start_date is None:
            r2 = await db.execute(text(
                "SELECT MAX(snapshot_date) FROM feature_snapshots"
            ))
            last = r2.fetchone()[0]
            if last:
                resume_from = last + timedelta(days=1) if hasattr(last, 'days') else (
                    date.fromisoformat(str(last)) + timedelta(days=1)
                )
                _logger.info(f"Auto-resuming from {resume_from} (last snapshot: {last})")
                start = resume_from
            else:
                start = db_min
        else:
            start = date.fromisoformat(start_date)

        end = date.fromisoformat(end_date) if end_date else db_max

    if start > end:
        _logger.info(f"Backfill already complete (start={start} > end={end})")
        return {"status": "already_complete", "days_processed": 0,
                "pairs_written": 0, "skipped_days": 0, "elapsed_seconds": 0}

    total_days     = (end - start).days + 1
    days_processed = 0
    pairs_written  = 0
    skipped_days   = 0

    _logger.info(f"Backfill range: {start} → {end} ({total_days} days)",
                 extra={"pipeline_name": "backfill_features"})

    # ── Load ALL sales data once into memory ──────────────────────────────────
    # Load from (start - 35 days) to end to have full lag context
    load_start = start - timedelta(days=_WINDOW_BEFORE)

    async with make_worker_session() as db:
        result = await db.execute(
            text("""
                SELECT store_id, item_id, date, sales, price, promo
                FROM   sales_transactions
                WHERE  date BETWEEN :s AND :e
                ORDER  BY store_id, item_id, date
            """),
            {"s": load_start, "e": end},   # date objects — asyncpg handles natively
        )
        rows = result.fetchall()
        cols = list(result.keys())

    if not rows:
        return {"status": "no_sales_data", "days_processed": 0,
                "pairs_written": 0, "skipped_days": 0, "elapsed_seconds": 0}

    _logger.info(f"Loaded {len(rows):,} sales rows into memory for feature computation",
                 extra={"pipeline_name": "backfill_features"})

    # ── Compute ALL features at once in pandas (vectorized) ───────────────────
    df = pd.DataFrame(rows, columns=cols)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["store_id", "item_id", "date"]).reset_index(drop=True)

    grp = df.groupby(["store_id", "item_id"])["sales"]

    # Lag features
    for lag in [7, 14, 21, 28, 35]:
        df[f"lag_{lag}"] = grp.transform(lambda x: x.shift(lag))

    # Rolling stats with shift(1) leakage guard
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

    # Calendar features
    df["_wd"] = df["date"].dt.weekday
    for d in range(7):
        df[f"wd_{d}"] = (df["_wd"] == d).astype("int8")
    doy   = df["date"].dt.dayofyear
    month = df["date"].dt.month
    df["month_sin"]     = np.sin(2 * np.pi * month / 12)
    df["month_cos"]     = np.cos(2 * np.pi * month / 12)
    df["doy_sin"]       = np.sin(2 * np.pi * doy / 365)
    df["doy_cos"]       = np.cos(2 * np.pi * doy / 365)
    df["week_of_month"] = (df["date"].dt.day - 1) // 7 + 1

    # Promo streak features
    def _streak(s: pd.Series) -> pd.Series:
        return s * (s.groupby((s != s.shift()).cumsum()).cumcount() + 1)

    def _days_since(s: pd.Series) -> pd.Series:
        return (s == 0).groupby((s != s.shift()).cumsum()).cumcount().where(s == 0, 0)

    pgrp = df.groupby(["store_id", "item_id"])["promo"]
    df["promo_streak_day"]      = pgrp.transform(_streak)
    df["days_since_last_promo"] = pgrp.transform(_days_since)
    df["history_days"]          = df.groupby(["store_id", "item_id"]).cumcount() + 1

    # Drop non-P1 lags
    df = df.drop(columns=[c for c in DROPPED_FEATURES if c in df.columns], errors="ignore")
    df = df.drop(columns=["_wd"], errors="ignore")

    # Filter to target date range only
    target_mask = (df["date"].dt.date >= start) & (df["date"].dt.date <= end)
    target_df   = df[target_mask].copy()
    target_df["snapshot_date"] = target_df["date"].dt.date  # Python date object, not string

    _logger.info(f"Feature computation complete: {len(target_df):,} rows to insert",
                 extra={"pipeline_name": "backfill_features"})

    # ── Bulk INSERT in 30-day batches ─────────────────────────────────────────
    # Prepare column list once
    insert_cols = (
        ["store_id", "item_id", "snapshot_date", "history_days"] + ALL_P1_FEATURES
    )

    # NaN → None for PostgreSQL compatibility
    def _row_to_vals(row: pd.Series) -> dict:
        vals: dict = {
            "store_id":      str(row["store_id"]),
            "item_id":       str(row["item_id"]),
            "snapshot_date": row["snapshot_date"],  # already a Python date from .dt.date
            "history_days":  int(row.get("history_days", 0)),
        }
        for col in ALL_P1_FEATURES:
            v = row.get(col, np.nan)
            vals[col] = (None if (v is None or (isinstance(v, float) and np.isnan(v)))
                         else float(v))
        return vals

    # SQL template (built once)
    col_list = ", ".join(insert_cols)
    val_placeholders = ", ".join(f":{c}" for c in insert_cols)
    update_set = ", ".join(
        f"{c}=EXCLUDED.{c}" for c in insert_cols
        if c not in ("store_id", "item_id", "snapshot_date")
    )
    insert_sql = text(f"""
        INSERT INTO feature_snapshots ({col_list})
        VALUES ({val_placeholders})
        ON CONFLICT (store_id, item_id, snapshot_date) DO UPDATE SET {update_set}
    """)

    # Batch by 30-day windows
    current_batch_start = start
    while current_batch_start <= end:
        current_batch_end = min(
            current_batch_start + timedelta(days=_BATCH_DAYS - 1), end
        )

        batch_mask = (
            (target_df["date"].dt.date >= current_batch_start) &
            (target_df["date"].dt.date <= current_batch_end)
        )
        batch_df = target_df[batch_mask]

        if batch_df.empty:
            skipped_days += (current_batch_end - current_batch_start).days + 1
            current_batch_start = current_batch_end + timedelta(days=1)
            continue

        batch_vals = [_row_to_vals(row) for _, row in batch_df.iterrows()]

        async with make_worker_session() as db:
            # Single executemany per batch — ONE round-trip for up to 75,000 rows
            await db.execute(insert_sql, batch_vals)
            await db.commit()

        batch_days  = (current_batch_end - current_batch_start).days + 1
        batch_pairs = len(batch_df)
        days_processed += batch_days
        pairs_written  += batch_pairs

        pct = days_processed / total_days * 100
        elapsed_s = (datetime.now(tz=timezone.utc) - t0).total_seconds()
        _logger.info(
            f"Backfill batch complete: {current_batch_start} → {current_batch_end} "
            f"({batch_pairs:,} rows, {pct:.1f}% total, {elapsed_s:.0f}s elapsed)",
            extra={"current_date": str(current_batch_end),
                   "progress_pct": round(pct, 1),
                   "pairs_written": pairs_written,
                   "elapsed_seconds": round(elapsed_s, 1),
                   "pipeline_name": "backfill_features"},
        )

        # Persist progress for resume capability
        try:
            async with make_worker_session() as db:
                await db.execute(
                    text("""
                        UPDATE system_bootstrap_status
                        SET last_backfill_date = :d, updated_at = now()
                        WHERE system_id = 'default'
                    """),
                    {"d": current_batch_end},  # date object
                )
                await db.commit()
        except Exception:
            pass  # non-fatal

        current_batch_start = current_batch_end + timedelta(days=1)

    elapsed = round((datetime.now(tz=timezone.utc) - t0).total_seconds(), 1)
    _logger.info(
        "Backfill pipeline complete",
        extra={"days_processed": days_processed, "pairs_written": pairs_written,
               "elapsed_seconds": elapsed, "pipeline_name": "backfill_features"},
    )
    return {
        "status":          "ok",
        "days_processed":  days_processed,
        "pairs_written":   pairs_written,
        "skipped_days":    skipped_days,
        "elapsed_seconds": elapsed,
    }


if __name__ == "__main__":
    asyncio.run(run())