"""
Feature constants — Category 1 (Scientific).

Derived from validated R&D notebooks. Change only after re-running the
corresponding notebook and getting a PR approved by a data scientist.

Change effect cascade:
    ANY change here → feature_snapshots table is stale → feature engineering
    must re-run for all history → model artifacts must retrain.

Source notebooks:
    retail_feature_engineering.ipynb  (feature manifest, leakage audit)
    retail_statistical_diagnostics.ipynb  (PACF, ACF, spectral analysis)
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Horizon & history constants
# ---------------------------------------------------------------------------

FORECAST_HORIZON_DAYS: int = 7
"""7-day ahead forecast. Derived from replenishment lead time constraint."""

MAX_USABLE_LAG_AT_INFERENCE: int = 7
"""lag_1..lag_6 are unavailable at h=7 inference — they refer to days not yet
observed when the forecast is generated."""

MIN_HISTORY_REQUIRED_ROWS: int = 28
"""Minimum days of history before a pair can use the full feature set.
Below this threshold, cold start routing applies."""

# ---------------------------------------------------------------------------
# P1 feature groups — 25 features total
# ---------------------------------------------------------------------------

P1_LAG_FEATURES: list[str] = ["lag_7", "lag_14", "lag_21"]
"""PACF-significant lags. lag_28/35 are NOT significant (see diagnostics notebook)."""

P1_ROLLING_MEAN_FEATURES: list[str] = [
    "rolling_mean_7",
    "rolling_mean_14",
    "rolling_mean_28",
]
"""rolling_mean_28 is critical: acts as a trend bridge allowing the tree model
to extrapolate the ~5.5% YoY growth without relearning from scratch."""

P1_ROLLING_STD_FEATURES: list[str] = ["rolling_std_7", "rolling_std_14"]
P1_ROLLING_CV_FEATURES: list[str] = ["rolling_cv_7", "rolling_cv_14"]

P1_CALENDAR_FEATURES: list[str] = [
    "wd_0", "wd_1", "wd_2", "wd_3", "wd_4", "wd_5", "wd_6",  # weekday one-hot
    "month_sin", "month_cos",   # cyclic — preserves Dec→Jan continuity
    "doy_sin", "doy_cos",       # yearly cycle (spectral: power 6.31e4)
    "week_of_month",            # intra-month position
]

P1_PROMO_FEATURES: list[str] = [
    "promo",                   # causal; matched-window +50.0% validated
    "promo_streak_day",        # H10 fatigue encoding
    "days_since_last_promo",   # H12 post-promo dip encoding
]

ALL_P1_FEATURES: list[str] = (
    P1_LAG_FEATURES
    + P1_ROLLING_MEAN_FEATURES
    + P1_ROLLING_STD_FEATURES
    + P1_ROLLING_CV_FEATURES
    + P1_CALENDAR_FEATURES
    + P1_PROMO_FEATURES
)
"""25 features total. Verified by test_feature_contract.py."""

# ---------------------------------------------------------------------------
# Inference / training split
# ---------------------------------------------------------------------------

INFERENCE_FEATURES: list[str] = ALL_P1_FEATURES
"""Features available at inference time (h=7). Excludes TRAINING_ONLY_FEATURES."""

TRAINING_ONLY_FEATURES: list[str] = ["lag_1", "lag_2", "lag_3"]
"""Available during training (same-day lookback is valid).
MUST NOT appear in INFERENCE_FEATURES — verified by test_feature_contract.py."""

DROPPED_FEATURES: list[str] = ["lag_28", "lag_35"]
"""PACF NOT significant; all 4-week information captured by lag_7/14/21.
Must never be written to feature_snapshots table."""

COLD_START_REDUCED_FEATURES: list[str] = [
    "lag_7",
    "rolling_mean_7",
    "promo",
    "wd_0", "wd_1", "wd_2", "wd_3", "wd_4", "wd_5", "wd_6",
    "month_sin", "month_cos",
]
"""Tier-2 cold start: features available after only 7 days of history."""

# ---------------------------------------------------------------------------
# Business label translation — single source of truth
# Used by explain_forecast.py; never hardcode labels in service files.
# ---------------------------------------------------------------------------

FEATURE_BUSINESS_LABELS: dict[str, str] = {
    "lag_7":                "Sales pattern from same day last week",
    "lag_14":               "Sales pattern from 2 weeks ago",
    "lag_21":               "Sales pattern from 3 weeks ago",
    "rolling_mean_7":       "Current 7-day demand trend",
    "rolling_mean_14":      "14-day demand baseline",
    "rolling_mean_28":      "28-day demand baseline",
    "rolling_std_7":        "Recent demand volatility",
    "rolling_std_14":       "14-day demand volatility",
    "rolling_cv_7":         "Relative demand variability (7-day)",
    "rolling_cv_14":        "Relative demand variability (14-day)",
    "promo":                "Promotion is active",
    "promo_streak_day":     "Consecutive promotion day",
    "days_since_last_promo": "Days since last promotion ended",
    "wd_0": "Monday",
    "wd_1": "Tuesday",
    "wd_2": "Wednesday (peak demand day)",
    "wd_3": "Thursday",
    "wd_4": "Friday",
    "wd_5": "Saturday (weekend dip)",
    "wd_6": "Sunday",
    "month_sin":      "Monthly seasonal cycle",
    "month_cos":      "Monthly seasonal cycle",
    "doy_sin":        "Yearly seasonal cycle",
    "doy_cos":        "Yearly seasonal cycle",
    "week_of_month":  "Week position within month",
}

# ---------------------------------------------------------------------------
# Top gain features for feature_snapshot (per-prediction debugging)
# ---------------------------------------------------------------------------

TOP_GAIN_FEATURES_FOR_SNAPSHOT: list[str] = [
    "lag_7",          # 32.02% gain
    "rolling_mean_28", # 14.97% gain
    "rolling_mean_14", # 14.96% gain
    "lag_14",          # 11.84% gain
    "promo",           # 4.74% gain — small gain, large business impact
]
"""Top-5 features by gain importance stored in DailyForecast.feature_snapshot.
Used for post-hoc debugging without re-running feature engineering."""
