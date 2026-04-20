"""
Model constants — Category 1 (Scientific).

Locked from validated R&D: ExpC_Fold1 | Test MAE 2.500 | Promo-MAE 2.641.
Source: retail_modeling.ipynb

Change effect cascade:
    QUANTILE_LEVEL changed  → all 3 model artifacts must retrain
    BEST_ITERATION changed  → model behavior changes at inference
    LGBM_PARAMS changed     → full training pipeline must re-run
"""
from __future__ import annotations

from datetime import date

# ---------------------------------------------------------------------------
# LightGBM base parameters — locked from R&D
# ---------------------------------------------------------------------------

LGBM_PARAMS_BASE: dict = {
    "device":            "cpu",
    "n_jobs":            -1,
    "boosting_type":     "gbdt",
    "num_leaves":        127,
    "min_child_samples": 50,
    "learning_rate":     0.05,
    "n_estimators":      1000,   # with early_stopping=50 during training
    "subsample":         0.8,
    "subsample_freq":    1,
    "colsample_bytree":  0.8,
    "reg_alpha":         0.1,
    "reg_lambda":        0.1,
    "random_state":      42,
}

# ---------------------------------------------------------------------------
# Quantile levels — three artifacts per training run
# ---------------------------------------------------------------------------

QUANTILE_LEVELS_ALL: list[float] = [0.40, 0.60, 0.80]
"""Three quantile models registered per training cycle.
q60 → primary production. q40 → lower bound. q80 → planning buffer."""

QUANTILE_PRODUCTION: float = 0.60
"""Primary production quantile. Derivation: ALPHA/(1+ALPHA) = 1.5/2.5 = 0.60.
Predicts 60th percentile — intentional upward bias reduces stockout risk."""

QUANTILE_LOWER_BOUND: float = 0.40
QUANTILE_UPPER_BOUND: float = 0.80

ASYMMETRIC_ALPHA: float = 1.5
"""Underforecast cost / overstock cost ratio. Business basis: stockout during
promo destroys revenue and customer loyalty; overstock is recoverable."""

# ---------------------------------------------------------------------------
# Production inference constants
# ---------------------------------------------------------------------------

BEST_ITERATION_PRODUCTION: int = 658
"""ExpC_Fold1 best_iter. Fixed at inference — no early stopping in production.
Source: retail_modeling.ipynb Section 9, model_results.json."""

CATEGORICAL_FEATURES: list[str] = []
"""Entity codes (store_code, item_code) caused overfit in R&D ablation.
P2 features dropped from all production experiments."""

# ---------------------------------------------------------------------------
# Training window strategy
# ---------------------------------------------------------------------------

TRAINING_WINDOW_STRATEGY: str = "expanding"
"""Options: 'expanding' | 'sliding'.
Expanding chosen because R&D showed 5.5% YoY growth — model benefits from
seeing long-term trend; sliding window would lose this signal."""

MIN_TRAINING_YEARS: int = 3
"""Minimum viable training history. lag_21 needs 21 days, rolling_mean_28
needs 28 days minimum; 3 years provides stable seasonal pattern."""

VALIDATION_HORIZON_MONTHS: int = 6
"""6-month validation window matches R&D fold structure."""

# ---------------------------------------------------------------------------
# Model promotion rules
# ---------------------------------------------------------------------------

PROMOTION_THRESHOLD_PCT: float = 30.0
"""New model must beat naive MAE_promo by 30% minimum to be promoted."""

CHAMPION_REPLACEMENT_THRESHOLD_PCT: float = 3.0
"""Challenger must beat champion MAE_promo by 3% to replace."""

MODEL_ARCHIVAL_DAYS: int = 90
"""Non-production MinIO artifacts deleted after 90 days.
Registry metadata retained permanently for audit."""

# ---------------------------------------------------------------------------
# Baseline metrics from R&D — used for alert thresholds
# ---------------------------------------------------------------------------

BASELINE_TEST_MAE_OVERALL: float = 2.500
"""ExpC_Fold1 on test 2023. Source: model_results.json."""

BASELINE_TEST_MAE_PROMO: float = 2.641
"""Primary business metric baseline. Source: model_results.json."""

BASELINE_TEST_UF_PROMO_PCT: float = 0.4729
"""Underforecast rate on promo days. Source: model_results.json."""

BASELINE_NAIVE_MAE: float = 5.609
"""Seasonal naive MAE on test 2023. Improvement baseline."""

ROLLING_ALERT_WINDOW_DAYS: int = 7
"""Primary alert window — avoids false alarms from single-day outliers."""

ROLLING_TREND_WINDOW_DAYS: int = 28
"""Secondary trend analysis window."""

# ---------------------------------------------------------------------------
# Cold start quality benchmarks — from analytics_validation.ipynb
# ---------------------------------------------------------------------------

COLD_START_ERROR_RATIO: float = 1.13
"""Tier-1 proxy MAE / full-history MAE. Source: analytics_validation notebook.
Used in ColdStartResult.confidence_note for API consumers."""

COLD_START_TIER2_ERROR_RATIO: float = 1.01
"""Tier-2 (lag_7 only) MAE / full-history MAE. Near-equivalent to full model."""

COLD_START_CONFIDENCE_NOTE: str = (
    "Expected error ~1.1x higher than established pairs."
)

# ---------------------------------------------------------------------------
# Walk-forward split strategy — dynamic (not hardcoded dates)
# ---------------------------------------------------------------------------

WALK_FORWARD_ORIGINAL_TRAIN_START: date = date(2019, 1, 1)
"""Earliest available training data. For expanding window strategy."""

RETRAINING_COOLDOWN_DAYS: int = 7
"""Minimum days between automatic retraining triggers to prevent thrashing."""

TRAINING_MEAN_SALES: float = 27.76
"""Global mean daily sales from R&D EDA (same as analytics_constants.TRAINING_MEAN_SALES)."""
