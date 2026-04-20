"""
Decision constants — Category 3 defaults for V2 Decision Intelligence layer.

These are startup defaults. All values marked Category 3 are overridden by
business_configs DB table at runtime (Redis TTL=300s).

To change in production: POST /config/business-rules (admin auth + reason required).
Changes are audited with previous_value, updated_by, updated_at.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Decision scoring weights — Category 3 (DB-overridable)
# ---------------------------------------------------------------------------

DEFAULT_DECISION_WEIGHTS: dict[str, float] = {
    "roi":          0.40,   # primary business objective
    "stock":        0.25,   # operational feasibility (higher than naive 0.20 —
    #                         inventory blind spot identified in architecture review)
    "uncertainty":  0.20,   # prediction confidence
    "substitution": 0.15,   # cross-item cannibalization risk
}
"""Derivation: ROI is the primary objective (0.40). Stock feasibility second
(0.25) because operational impossibility overrides financial attractiveness.
Weights must sum to 1.0 — enforced by test_feature_contract.py."""

DEFAULT_DECISION_APPROVE_THRESHOLD: float = 0.70
"""Composite score ≥ 0.70 → APPROVE."""

DEFAULT_DECISION_REVIEW_THRESHOLD: float = 0.40
"""0.40 ≤ score < 0.70 → REVIEW. Below 0.40 → REJECT."""

# ---------------------------------------------------------------------------
# Monte Carlo uncertainty propagation — Category 1 (scientific)
# ---------------------------------------------------------------------------

UNCERTAINTY_N_SCENARIOS: int = 1000
"""1000 MC scenarios provides stable p10/p50/p90 without excessive compute.
At 1000 samples: variance in probability_profitable < 0.02 across seeds."""

# ---------------------------------------------------------------------------
# COGS assumption scenarios — Category 3 defaults
# ---------------------------------------------------------------------------

COGS_DEFAULT_SCENARIO: str = "NORMAL_MARGIN"
"""Fallback when item_id not found in item_financial_assumptions table.
Risk Note is appended to RecommendationObject when fallback is used."""

COGS_SCENARIOS: dict[str, dict[str, float]] = {
    "LOW_MARGIN": {
        "cogs_pct":          0.75,   # 25% gross margin
        "promo_fixed_cost":  50.0,
        "holding_cost_day":  0.02,   # key matches test_feature_contract
    },
    "NORMAL_MARGIN": {
        "cogs_pct":          0.60,   # 40% gross margin
        "promo_fixed_cost":  100.0,
        "holding_cost_day":  0.015,
    },
    "HIGH_MARGIN": {
        "cogs_pct":          0.40,   # 60% gross margin
        "promo_fixed_cost":  150.0,
        "holding_cost_day":  0.010,
    },
}

# ---------------------------------------------------------------------------
# Config snapshot — which Category 3 keys to freeze per simulation
# ---------------------------------------------------------------------------

SIMULATION_CONFIG_SNAPSHOT_KEYS: list[str] = [
    "DECISION_WEIGHTS",
    "DECISION_APPROVE_THRESHOLD",
    "DECISION_REVIEW_THRESHOLD",
    "SAFETY_FACTOR_PROMO",
    "SAFETY_FACTOR_NORMAL",
    "SAFETY_FACTOR_COLD_START",
    "COGS_DEFAULT_SCENARIO",
]
"""Captured into decision_simulations.config_snapshot at creation time.
Enables reproducibility: past decisions can be re-explained with the exact
parameter set active at simulation time."""

# ---------------------------------------------------------------------------
# Feedback loop — Category 1 (scientific timing rules)
# ---------------------------------------------------------------------------

FEEDBACK_LOOP_MIN_LOOKBACK_DAYS: int = 7
"""Minimum age of simulation before feedback is resolved.
Ensures actuals have stabilized (sales data fully ingested)."""

FEEDBACK_LOOP_MAX_LOOKBACK_DAYS: int = 14
"""Maximum age. Simulations older than 14 days without resolution → UNRESOLVED."""

ELASTICITY_ROLLING_ALPHA: float = 0.3
"""EMA weight for elasticity recalibration.
new_estimate = 0.3 × actual_proxy + 0.7 × current_estimate.
Conservative: recent observation gets 30% weight, history 70%."""

ELASTICITY_DEVIATION_FLAG_PCT: float = 20.0
"""Flag simulation for manual review if |predicted - actual| > 20%."""

# ---------------------------------------------------------------------------
# Cross-item impact dampening factors — Category 1 (scientific)
# ---------------------------------------------------------------------------

CANNIBALIZATION_DAMPENING: float = 0.5
"""Fraction of correlation that translates to actual demand transfer (substitution).
Conservative: correlation ≠ perfect causation."""

HALO_DAMPENING: float = 0.3
"""Fraction of correlation that translates to actual demand gain (complementary).
Weaker than substitution — halo effect is less direct."""

SUBSTITUTE_CORRELATION_THRESHOLD: float = -0.20
"""Items with correlation < -0.20 classified as SUBSTITUTE."""

COMPLEMENTARY_CORRELATION_THRESHOLD: float = 0.50
"""Items with correlation > 0.50 classified as COMPLEMENTARY."""

# ---------------------------------------------------------------------------
# Simulation drift monitoring — Category 3 thresholds
# ---------------------------------------------------------------------------

APPROVAL_SUCCESS_RATE_ALERT_THRESHOLD: float = 0.50
"""Alert ML team if approval_success_rate_7d drops below 50%."""

OVERRIDE_RATE_WARNING_THRESHOLD: float = 0.30
"""Log WARNING if override_rate_7d exceeds 30% — weight recalibration needed."""
