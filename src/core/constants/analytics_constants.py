"""
Analytics constants — Category 1 (Scientific baselines).

All values derived from validated EDA and analytics_validation notebooks.
Source: retail_eda.ipynb, retail_statistical_diagnostics.ipynb,
        retail_analytics_validation.ipynb
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# EDA baselines — retail_eda.ipynb
# ---------------------------------------------------------------------------

BASELINE_PROMO_UPLIFT_PCT: float = 50.24
"""Global raw comparison (promo vs non-promo). Welch t-test p≈0."""

BASELINE_MATCHED_WINDOW_UPLIFT: float = 50.0
"""Most reliable causal estimate. Three methods converged: 50.0, 50.08, 50.24."""

BASELINE_ACF_LAG7_GLOBAL: float = 0.993
"""Global daily series ACF at lag 7."""

BASELINE_ACF_LAG7_PAIR: float = 0.703
"""Representative single store-item pair ACF at lag 7."""

BASELINE_WED_SAT_RATIO: float = 1.484
"""Wednesday / Saturday avg sales ratio. Source: 34.97 / 23.57."""

BASELINE_WED_UPLIFT_PCT: float = 19.5
"""Wednesday demand above weekly mean (%)."""

BASELINE_SAT_TROUGH_PCT: float = -19.5
"""Saturday demand below weekly mean (%)."""

BASELINE_PEAK_MONTH: str = "Apr"
BASELINE_TROUGH_MONTH: str = "Oct"
BASELINE_SEASONAL_SPREAD: float = 16.12
"""Peak-to-trough seasonal spread in units."""

BASELINE_YOY_GROWTH_PCT: float = 5.5
"""Average annual growth rate (2019-2023). Linear, consistent."""

BASELINE_PRICE_SALES_CORR: float = -0.060
"""Global Pearson r (price vs sales, all days). Weak but significant."""

BASELINE_PAIR_LEVEL_CV: float = 32.65
"""Average CV across all 2500 pairs (%)."""

TRAINING_MEAN_SALES: float = 27.76
"""Mean daily sales during training period (2019-2021).
Used as reference for target distribution drift detection."""

# ---------------------------------------------------------------------------
# Analytics validation baselines — retail_analytics_validation.ipynb
# ---------------------------------------------------------------------------

BASELINE_PROMO_REVENUE_UPLIFT_PCT: float = 20.20
"""Revenue uplift during promo. Lower than unit uplift due to price discount."""

BASELINE_UNIT_VS_REVENUE_DIVERGENCE: float = 30.04
"""Unit uplift (50.24%) minus revenue uplift (20.20%). Positive = revenue diluted."""

PROMO_BREAKEVEN_UPLIFT_PCT: float = 24.92
"""Minimum unit uplift needed to break even on revenue at observed discount rate."""

PROMO_AVG_OBSERVED_DISCOUNT_PCT: float = 19.95
"""Average price discount during promo vs non-promo days."""

PROMO_EFF_MEDIAN_UNIT_UPLIFT: float = 50.03
"""Median unit uplift across eligible items (≥20 promo days)."""

KNOWN_CROSS_ITEM_CORRELATION_MEDIAN: float = 0.649
"""Median off-diagonal item correlation. Basis for V2 cannibalization layer.
Justifies independent demand assumption for V1 (within store, not between stores)."""

ELASTICITY_ELASTIC_ITEM_THRESHOLD: float = -0.10
"""Pearson r below this → item classified as price-elastic."""

TARGET_DRIFT_ALERT_PCT: float = 15.0
"""Alert if rolling 28-day mean sales deviates > 15% from TRAINING_MEAN_SALES."""

HIGH_DEMAND_THRESHOLD_PCT: float = (
    11.0  # P95 deviation — filled in after analytics notebook run
)
"""P95 demand deviation threshold for high-demand day classification."""

# ---------------------------------------------------------------------------
# Hypothesis alert thresholds
# ---------------------------------------------------------------------------

HYPOTHESIS_ALERT_THRESHOLDS: dict[str, tuple] = {
    "H1_WEEKLY_CYCLE":    ("min_ratio",      1.20),
    "H5_PROMO_CAUSALITY": ("min",            35.0),
    "H_TREND_YOY":        ("direction",      "negative_2_months"),
    "H_PRICE_ELASTICITY": ("drift_abs",       0.02),
    "H_PROMO_FREQ":       ("max_monthly_days", 20),
    "H_TAIL_COMPOSITION": ("min_promo_in_spikes", 0.60),
}
"""Alert thresholds per hypothesis. Format: (check_type, threshold_value).
Used by RunHypothesisMonitorService."""

# ── Constants referenced by services but missing from initial definition ──────

P99_SALES_THRESHOLD: int = 73
"""P99 of daily sales distribution from EDA. Spike alert threshold."""

BASELINE_PRICE_SALES_CORR_GLOBAL: float = -0.060
"""Global price-sales Pearson r (non-promo days). From analytics notebook."""

PROMO_FATIGUE_FREQ_THRESHOLD: int = 20
"""Max promo days per month per item before promo fatigue hypothesis fires."""

ELASTICITY_ROLLING_ALPHA: float = 0.30
"""EMA weight for feedback-loop elasticity recalibration.
new_estimate = 0.30 × actual_proxy + 0.70 × current_estimate"""

APPROVAL_SUCCESS_RATE_ALERT_THRESHOLD: float = 0.60
"""Alert if APPROVED promos have actual profitability rate below this."""

OVERRIDE_RATE_WARNING_THRESHOLD: float = 0.30
"""Alert if human override rate exceeds 30% — suggests score weights need tuning."""

SYSTEM_AVG_STORE_YOY_GROWTH: float = 5.5
"""Average YoY growth rate across all stores (from EDA). Used in store analytics."""
