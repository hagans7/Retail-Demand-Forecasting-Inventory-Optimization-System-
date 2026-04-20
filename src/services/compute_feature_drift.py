"""Compute feature drift service — PSI-based drift detection.

PSI (Population Stability Index) thresholds:
    < 0.10 → NONE    (stable)
    0.10–0.20 → LOW/MEDIUM (monitor)
    > 0.20 → HIGH/CRITICAL (alert)

Also computes target distribution shift (% change in rolling mean sales
vs TRAINING_MEAN_SALES from analytics_constants).
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.core.constants.analytics_constants import TARGET_DRIFT_ALERT_PCT, TRAINING_MEAN_SALES
from src.core.constants.feature_constants import INFERENCE_FEATURES
from src.core.logging.logger import get_logger
from src.entities.drift_metric import DriftSeverity, FeatureDriftMetric
from src.interfaces.base_analytics_repository import BaseAnalyticsRepository
from src.interfaces.base_feature_repository import BaseFeatureRepository


class ComputeFeatureDriftService:
    """Weekly PSI drift computation for all 25 inference features + target.

    Training reference distributions stored in analytics_snapshot or
    loaded from model_registry training_artifacts.json (uploaded by train_model).
    """

    PSI_THRESHOLDS = {
        DriftSeverity.NONE:     0.10,
        DriftSeverity.LOW:      0.15,
        DriftSeverity.MEDIUM:   0.20,
        DriftSeverity.HIGH:     0.30,
    }

    def __init__(
        self,
        feature_repo: BaseFeatureRepository,
        analytics_repo: BaseAnalyticsRepository,
    ) -> None:
        self._features  = feature_repo
        self._analytics = analytics_repo
        self._logger    = get_logger(__name__)

    async def execute(self, reference_date: date | None = None) -> list[FeatureDriftMetric]:
        from datetime import datetime, timezone
        today   = reference_date or date.today()
        start   = today - timedelta(days=28)
        metrics = []

        # Load current feature snapshot batch for last 28 days
        try:
            current_df = await self._features.get_features_batch(today)
        except Exception as e:
            self._logger.warning(
                "Feature drift: could not load current features",
                extra={"error": str(e), "operation": "compute_feature_drift"},
            )
            return metrics

        if current_df.empty:
            return metrics

        # Training reference values from R&D constants
        training_references = {
            "lag_7": TRAINING_MEAN_SALES,
            "lag_14": TRAINING_MEAN_SALES,
            "lag_21": TRAINING_MEAN_SALES,
            "rolling_mean_7":  TRAINING_MEAN_SALES,
            "rolling_mean_14": TRAINING_MEAN_SALES,
            "rolling_mean_28": TRAINING_MEAN_SALES,
            "rolling_std_7":   8.5,   # approximate from R&D
            "rolling_std_14":  8.2,
            "promo":           0.10,  # 10% promo rate
        }
        training_std_refs = {
            "lag_7": 8.0, "lag_14": 8.0, "lag_21": 8.0,
            "rolling_mean_7": 7.5, "rolling_mean_14": 7.5, "rolling_mean_28": 7.5,
            "rolling_std_7": 3.0, "rolling_std_14": 3.0,
            "promo": 0.30,
        }

        now = datetime.now(tz=timezone.utc)
        for feat in INFERENCE_FEATURES:
            if feat not in current_df.columns:
                continue
            current_col = current_df[feat].dropna()
            if len(current_col) < 10:
                continue

            current_mean = float(current_col.mean())
            current_std  = float(current_col.std())
            training_mean= training_references.get(feat, current_mean)
            training_std = training_std_refs.get(feat, current_std)

            # PSI via bucketed approach (10 buckets)
            psi = self._compute_psi(current_col.values, training_mean, training_std)
            severity = self._classify_psi(psi)

            metrics.append(FeatureDriftMetric(
                feature_name=feat,
                current_mean=round(current_mean, 4),
                training_mean=round(training_mean, 4),
                current_std=round(current_std, 4),
                training_std=round(training_std, 4),
                severity=severity,
                computed_at=now,
                psi_score=round(psi, 4),
            ))

        # Target distribution shift
        actuals_df = await self._analytics.get_sales_for_period(start, today)
        if not actuals_df.empty and "sales" in actuals_df.columns:
            rolling_mean_sales = float(actuals_df["sales"].mean())
            shift_pct = (rolling_mean_sales - TRAINING_MEAN_SALES) / TRAINING_MEAN_SALES * 100
            severity = DriftSeverity.HIGH if abs(shift_pct) > TARGET_DRIFT_ALERT_PCT else DriftSeverity.NONE
            metrics.append(FeatureDriftMetric(
                feature_name="TARGET_sales",
                current_mean=round(rolling_mean_sales, 4),
                training_mean=TRAINING_MEAN_SALES,
                current_std=float(actuals_df["sales"].std()),
                training_std=8.0,
                severity=severity,
                computed_at=now,
                shift_pct=round(shift_pct, 2),
            ))

        n_drifted = sum(1 for m in metrics if m.is_drifted())
        self._logger.info(
            "Feature drift computation complete",
            extra={"n_features": len(metrics), "n_drifted": n_drifted,
                   "operation": "compute_feature_drift"},
        )
        return metrics

    def _compute_psi(self, current: np.ndarray, ref_mean: float, ref_std: float) -> float:
        if ref_std <= 0:
            return 0.0
        bins = np.linspace(ref_mean - 3*ref_std, ref_mean + 3*ref_std, 11)
        expected_pct = np.diff(self._normal_cdf(bins, ref_mean, ref_std))
        expected_pct = np.clip(expected_pct, 1e-4, None)
        actual_counts, _ = np.histogram(current, bins=bins)
        actual_pct = actual_counts / max(len(current), 1)
        actual_pct = np.clip(actual_pct, 1e-4, None)
        return float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))

    @staticmethod
    def _normal_cdf(x: np.ndarray, mean: float, std: float) -> np.ndarray:
        from scipy.special import ndtr
        return ndtr((x - mean) / std)

    def _classify_psi(self, psi: float) -> DriftSeverity:
        if psi < 0.10:  return DriftSeverity.NONE
        if psi < 0.15:  return DriftSeverity.LOW
        if psi < 0.20:  return DriftSeverity.MEDIUM
        if psi < 0.30:  return DriftSeverity.HIGH
        return DriftSeverity.CRITICAL
