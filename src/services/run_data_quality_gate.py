"""Data quality gate service — pre-flight checks before feature engineering.

Checks (in order):
    CHECK-1 CRITICAL: sales_transactions table not empty
    CHECK-2 CRITICAL: no NULL in (store_id, item_id, date, sales, price, promo)
    CHECK-3 CRITICAL: sales >= 0 everywhere
    CHECK-4 WARNING:  data freshness — most recent date within DATA_FRESHNESS_HOURS_MAX
    CHECK-5 WARNING:  promo flag only 0 or 1 (no corruption)
    CHECK-6 INFO:     zero-sales anomaly scan — pairs with excessive zero streaks
    CHECK-7 INFO:     price outlier detection — price > 10× item median

Pipeline is BLOCKED if any CRITICAL check fails.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone, timedelta

import pandas as pd

from src.core.constants.business_constants import DATA_FRESHNESS_HOURS_MAX, ZERO_SALES_CONSECUTIVE_ALERT
from src.core.exceptions.app_exceptions import DataQualityGateFailedError
from src.core.logging.logger import get_logger
from src.entities.data_quality_event import DataQualityCheck, DataQualityEvent
from src.interfaces.base_analytics_repository import BaseAnalyticsRepository


class RunDataQualityGateService:
    """Pre-flight quality gate. Called by data_quality_gate_pipeline daily."""

    def __init__(self, analytics_repo: BaseAnalyticsRepository) -> None:
        self._analytics = analytics_repo
        self._logger    = get_logger(__name__)

    async def execute(self, run_date: date | None = None) -> DataQualityEvent:
        today    = run_date or date.today()
        run_id   = str(uuid.uuid4())
        checks   = []

        # Load 7-day window for most checks
        start = today - timedelta(days=7)
        try:
            df = await self._analytics.get_sales_for_period(start, today)
        except Exception as e:
            self._logger.error(
                "Data quality gate: failed to load data",
                extra={"error": str(e), "operation": "run_data_quality_gate"},
            )
            checks.append(DataQualityCheck(
                "CHECK-1-DATA-LOAD", False, "CRITICAL",
                f"Failed to query sales_transactions: {e}"
            ))
            return self._build_event(run_id, today, checks)

        # CHECK-1: table not empty
        checks.append(DataQualityCheck(
            "CHECK-1-TABLE-NOT-EMPTY",
            len(df) > 0,
            "CRITICAL",
            f"Rows in last 7 days: {len(df)}",
        ))

        if df.empty:
            return self._build_event(run_id, today, checks)

        # CHECK-2: no nulls in critical columns
        critical_cols = ["store_id", "item_id", "date", "sales", "price", "promo"]
        available = [c for c in critical_cols if c in df.columns]
        null_counts = df[available].isnull().sum()
        has_nulls = null_counts.sum() > 0
        checks.append(DataQualityCheck(
            "CHECK-2-NO-NULLS-IN-CRITICAL-COLS",
            not has_nulls,
            "CRITICAL",
            f"Null counts: {null_counts[null_counts > 0].to_dict()}" if has_nulls else "OK",
        ))

        # CHECK-3: sales >= 0
        if "sales" in df.columns:
            neg_count = (df["sales"] < 0).sum()
            checks.append(DataQualityCheck(
                "CHECK-3-SALES-NON-NEGATIVE",
                neg_count == 0,
                "CRITICAL",
                f"Negative sales rows: {neg_count}",
            ))

        # CHECK-4: data freshness
        if "date" in df.columns:
            most_recent = pd.to_datetime(df["date"]).max()
            now = datetime.now(tz=timezone.utc)
            staleness_hours = (now - most_recent.tz_localize("UTC") if most_recent.tzinfo is None
                               else now - most_recent).total_seconds() / 3600
            fresh = staleness_hours <= DATA_FRESHNESS_HOURS_MAX
            checks.append(DataQualityCheck(
                "CHECK-4-DATA-FRESHNESS",
                fresh,
                "WARNING",
                f"Most recent date: {most_recent.date()}, staleness: {staleness_hours:.1f}h (max={DATA_FRESHNESS_HOURS_MAX}h)",
            ))

        # CHECK-5: promo flag integrity
        if "promo" in df.columns:
            bad_promo = (~df["promo"].isin([0, 1])).sum()
            checks.append(DataQualityCheck(
                "CHECK-5-PROMO-FLAG-VALID",
                bad_promo == 0,
                "WARNING",
                f"Rows with promo not in {{0,1}}: {bad_promo}",
            ))

        # CHECK-6: zero-sales anomaly info
        if "sales" in df.columns:
            zero_pct = (df["sales"] == 0).mean() * 100
            checks.append(DataQualityCheck(
                "CHECK-6-ZERO-SALES-RATE",
                zero_pct < 5.0,
                "INFO",
                f"Zero-sales rate: {zero_pct:.2f}% (alert if >5%)",
            ))

        # CHECK-7: price outlier
        if "price" in df.columns and "item_id" in df.columns:
            item_median = df.groupby("item_id")["price"].median()
            df_m = df.merge(item_median.rename("price_median"), on="item_id")
            outliers = (df_m["price"] > df_m["price_median"] * 10).sum()
            checks.append(DataQualityCheck(
                "CHECK-7-PRICE-OUTLIER",
                outliers == 0,
                "INFO",
                f"Price outlier rows (>10× median): {outliers}",
            ))

        event = self._build_event(run_id, today, checks)
        self._logger.info(
            "Data quality gate complete",
            extra={
                "run_id": run_id, "all_critical_passed": event.all_critical_passed,
                "pipeline_blocked": event.pipeline_blocked,
                "n_checks": len(checks), "operation": "run_data_quality_gate",
            },
        )
        return event

    def _build_event(self, run_id: str, today: date, checks: list) -> DataQualityEvent:
        all_critical = all(c.passed for c in checks if c.severity == "CRITICAL")
        return DataQualityEvent(
            run_id=run_id,
            run_date=today,
            checks=checks,
            all_critical_passed=all_critical,
            pipeline_blocked=not all_critical,
            fallback_strategy="USE_LAST_GOOD_SNAPSHOT" if not all_critical else "NONE",
        )
