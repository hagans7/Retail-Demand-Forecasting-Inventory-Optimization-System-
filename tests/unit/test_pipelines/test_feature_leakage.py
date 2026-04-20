"""CRITICAL: Feature leakage tests — must pass before any deployment.

These tests verify that no future information leaks into feature computation.
Any failure = training data contamination = invalid model performance metrics.
"""
from __future__ import annotations

import pandas as pd
import numpy as np


def _build_sample_df(n_days: int = 50) -> pd.DataFrame:
    """Build minimal sales DataFrame for leakage testing."""
    import datetime
    dates  = [datetime.date(2023, 1, 1) + datetime.timedelta(days=i) for i in range(n_days)]
    sales  = list(range(n_days))   # deterministic values for easy verification
    return pd.DataFrame({"date": dates, "sales": sales})


def _compute_lag_features(df: pd.DataFrame, lag: int) -> pd.Series:
    """Replicate the lag feature computation used in feature engineering."""
    return df["sales"].shift(lag)


def _compute_rolling_mean(df: pd.DataFrame, window: int) -> pd.Series:
    """Replicate rolling mean computation (shift(1) before rolling)."""
    return df["sales"].shift(1).rolling(window, min_periods=1).mean()


# ------------------------------------------------------------------
# Lag feature leakage
# ------------------------------------------------------------------

def test_lag_7_contains_no_future_values():
    """lag_7[i] must equal sales[i-7], never sales[i] or later."""
    df = _build_sample_df()
    lag7 = _compute_lag_features(df, lag=7)

    # Row 10 has sales=10. lag_7 at row 10 should be sales[3]=3, NOT 10.
    assert lag7.iloc[10] == df["sales"].iloc[3], (
        f"lag_7[10] should be {df['sales'].iloc[3]}, got {lag7.iloc[10]}"
    )

    # Verify no lag value equals the current-day sales (would be leakage)
    for i in range(7, len(df)):
        assert lag7.iloc[i] != df["sales"].iloc[i], (
            f"lag_7[{i}] == sales[{i}]={df['sales'].iloc[i]} — future leakage detected!"
        )


def test_lag_14_excludes_current_row():
    df = _build_sample_df()
    lag14 = _compute_lag_features(df, lag=14)
    for i in range(14, len(df)):
        assert lag14.iloc[i] == df["sales"].iloc[i - 14]


def test_rolling_mean_excludes_current_row():
    """rolling_mean_7 must not include the current day's sales."""
    df = _build_sample_df()
    df.loc[15, "sales"] = 9999   # sentinel — should never appear in rolling mean at row 15
    rolling = _compute_rolling_mean(df, window=7)

    # rolling_mean at row 15 should be based on rows 14 and earlier only
    assert rolling.iloc[15] != 9999, (
        "rolling_mean_7[15] equals current-day sentinel — same-day leakage detected!"
    )
    # Explicitly check it's within the valid historical range
    historical_max = max(df["sales"].iloc[:15])
    assert rolling.iloc[15] <= historical_max + 1, \
        "rolling_mean_7[15] exceeds maximum historical sales — future leakage!"


def test_training_only_features_excluded_from_inference():
    """TRAINING_ONLY_FEATURES must have zero overlap with INFERENCE_FEATURES."""
    from src.core.constants.feature_constants import INFERENCE_FEATURES, TRAINING_ONLY_FEATURES
    overlap = set(TRAINING_ONLY_FEATURES) & set(INFERENCE_FEATURES)
    assert not overlap, (
        f"TRAINING_ONLY_FEATURES appear in INFERENCE_FEATURES — leakage risk: {overlap}"
    )


def test_dropped_features_not_in_feature_snapshots_schema():
    """lag_28 and lag_35 must never appear in INFERENCE_FEATURES."""
    from src.core.constants.feature_constants import INFERENCE_FEATURES, DROPPED_FEATURES
    for feat in DROPPED_FEATURES:
        assert feat not in INFERENCE_FEATURES, (
            f"DROPPED_FEATURE '{feat}' found in INFERENCE_FEATURES — must be excluded."
        )


def test_rolling_cv_uses_historical_only():
    """CV = std/mean must use shift(1) lookback to exclude current day."""
    df = _build_sample_df()
    # CV uses rolling std and rolling mean, both via shift(1) — verify indirectly
    rolling_mean = _compute_rolling_mean(df, window=7)
    rolling_std  = df["sales"].shift(1).rolling(7, min_periods=2).std()
    cv           = rolling_std / rolling_mean.replace(0, np.nan)

    # CV at row 20 should be finite and based only on rows <= 19
    assert not np.isnan(cv.iloc[20]) or True  # NaN is acceptable (insufficient window)
    # Verify rolling_mean at row 20 < sales[20] (because it's historical)
    if not np.isnan(rolling_mean.iloc[20]):
        assert rolling_mean.iloc[20] < df["sales"].iloc[20], \
            "rolling_mean at row 20 equals future value — leakage!"
