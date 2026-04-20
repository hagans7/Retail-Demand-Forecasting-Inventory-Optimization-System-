"""
Business constants — Category 1 (safe bounds) + Category 3 defaults.

Category 1 values (SAFETY_BOUNDS) are hardcoded and cannot be exceeded
via the /config/business-rules API under any circumstances.

Category 3 defaults are the startup values. They are overridden by the
business_configs DB table at runtime. Redis TTL=300s for cache invalidation.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Safety factors — Category 3 defaults (DB-overridable)
# ---------------------------------------------------------------------------

SAFETY_FACTOR_NORMAL: float = 1.10
"""10% buffer on non-promo days. Source: analytics validation notebook,
SERVICE_LEVEL_AT_FACTOR_110 ≈ 65.9%."""

SAFETY_FACTOR_PROMO: float = 1.20
"""20% buffer on promo days. Source: 76.9% of P99 spikes = promo days."""

SAFETY_FACTOR_COLD_START: float = 1.30
"""30% buffer for new pairs. Source: cold start error ratio ~1.13x."""

# ---------------------------------------------------------------------------
# Stockout risk thresholds — Category 3 defaults
# ---------------------------------------------------------------------------

STOCKOUT_CRITICAL_DAYS: int = 1
STOCKOUT_HIGH_DAYS: int = 3
STOCKOUT_MEDIUM_DAYS: int = 5

# ---------------------------------------------------------------------------
# Tail risk — Category 1 (scientific)
# ---------------------------------------------------------------------------

P99_SALES_THRESHOLD: int = 73
"""From R&D tail risk analysis. 76.9% of P99 rows are promo days."""

# ---------------------------------------------------------------------------
# Promo operational rules — Category 3 defaults
# ---------------------------------------------------------------------------

PROMO_SIM_EMPIRICAL_BASELINE: float = 50.0
"""Causal uplift baseline. Alert if simulation deviation > 10 pp."""

PROMO_MIN_EXPOSURE_DAYS: int = 20
"""Minimum promo days for reliable uplift estimate in endpoint ranking."""

PROMO_FATIGUE_RECOVERY_DAYS: int = 1
"""Days after promo ends before demand returns to 95% non-promo baseline.
Source: analytics_validation notebook Section B."""

PROMO_FATIGUE_FREQ_THRESHOLD: int = 20
"""Max promo days/month per item before fatigue flag triggers."""

# ---------------------------------------------------------------------------
# Monitoring alert thresholds — Category 3 defaults
# ---------------------------------------------------------------------------

PROMO_UF_ALERT_THRESHOLD: float = 0.65
"""UF rate > 65% on promo days → retraining alert."""

FORECAST_BIAS_ALERT_THRESHOLD: float = 2.0
"""abs(MeanBias) > 2.0 units → alert."""

MAE_PROMO_DEGRADATION_PCT: float = 25.0
"""Rolling-7d promo MAE rises 25% above baseline → retraining alert."""

DATA_FRESHNESS_HOURS_MAX: int = 6
"""Data older than 6 hours → freshness alert."""

# ---------------------------------------------------------------------------
# Cold start routing thresholds — Category 1 (scientific)
# ---------------------------------------------------------------------------

COLD_START_TIER1_DAYS: int = 7
"""history_days < 7 → TIER1_PROXY (cross-store average)."""

COLD_START_TIER2_DAYS: int = 28
"""7 <= history_days < 28 → TIER2_REDUCED (lag_7 only)."""

# ---------------------------------------------------------------------------
# Zero-sales anomaly — Category 3 defaults
# ---------------------------------------------------------------------------

ZERO_SALES_CONSECUTIVE_ALERT: int = 3
"""Consecutive zero-sales days → anomaly alert.
Source: analytics_validation notebook, Section C."""

STRUCTURAL_ZERO_RATE_THRESHOLD: float = 10.0
"""Pairs with zero_rate > 10% excluded from anomaly flagging."""

# ---------------------------------------------------------------------------
# Markdown / clearance — Category 3 defaults
# ---------------------------------------------------------------------------

DEAD_STOCK_ZERO_STREAK_THRESHOLD: int = 4
"""Zero-sales streak triggering clearance recommendation (1 beyond alert)."""

CLEARANCE_DEMAND_DECLINE_PCT: float = 30.0
"""Rolling 7d vs 28d decline % contributing to dead-stock signal."""

# ---------------------------------------------------------------------------
# Store underperformance — Category 3 (filled after analytics run)
# ---------------------------------------------------------------------------

STORE_UNDERPERFORMANCE_THRESHOLD_PCT: float = 4.0
"""YoY growth below this flags store as underperforming (system_avg - 1σ)."""

SYSTEM_AVG_STORE_YOY_GROWTH: float = 5.5
"""Average YoY growth rate across all stores."""

# ---------------------------------------------------------------------------
# Service level empirical values — Category 1 (scientific)
# ---------------------------------------------------------------------------

SERVICE_LEVEL_AT_FACTOR_110: float = 65.9
SERVICE_LEVEL_AT_FACTOR_120: float = 75.4
SERVICE_LEVEL_AT_FACTOR_130: float = 83.1
"""Source: analytics_validation notebook Section E."""

PROMO_BUFFER_FOR_P80_COVERAGE: float = 1.409
"""Safety factor needed to cover P80 demand on promo days empirically."""

# ---------------------------------------------------------------------------
# SAFETY_BOUNDS — Category 1 (hardcoded, cannot be exceeded via API)
# ---------------------------------------------------------------------------

SAFETY_BOUNDS: dict[str, tuple[float, float]] = {
    "SAFETY_FACTOR_PROMO":           (1.0, 2.0),
    "SAFETY_FACTOR_NORMAL":          (1.0, 1.5),
    "SAFETY_FACTOR_COLD_START":      (1.0, 2.0),
    "PROMO_UF_ALERT_THRESHOLD":      (0.30, 0.90),
    "FORECAST_BIAS_ALERT_THRESHOLD": (0.5, 5.0),
    "DECISION_APPROVE_THRESHOLD":    (0.50, 0.90),
    "DECISION_REVIEW_THRESHOLD":     (0.20, 0.60),
    "DECISION_WEIGHT_ROI":           (0.10, 0.70),
    "DECISION_WEIGHT_STOCK":         (0.10, 0.50),
    "DECISION_WEIGHT_UNCERTAINTY":   (0.05, 0.40),
    "DECISION_WEIGHT_SUBSTITUTION":  (0.05, 0.40),
}
