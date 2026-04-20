"""CRITICAL: Feature contract tests — must pass before any deployment.

These tests lock the scientific constants derived from R&D notebooks.
Any failure means the codebase is inconsistent with the validated R&D.
"""
from __future__ import annotations


def test_p1_feature_count_is_25():
    from src.core.constants.feature_constants import ALL_P1_FEATURES
    assert len(ALL_P1_FEATURES) == 25, (
        f"ALL_P1_FEATURES must have exactly 25 features, got {len(ALL_P1_FEATURES)}"
    )


def test_no_duplicate_features_in_p1():
    from src.core.constants.feature_constants import ALL_P1_FEATURES
    assert len(ALL_P1_FEATURES) == len(set(ALL_P1_FEATURES)), \
        "ALL_P1_FEATURES contains duplicate feature names"


def test_dropped_features_not_in_p1():
    from src.core.constants.feature_constants import ALL_P1_FEATURES, DROPPED_FEATURES
    overlap = set(DROPPED_FEATURES) & set(ALL_P1_FEATURES)
    assert not overlap, f"DROPPED_FEATURES found in ALL_P1_FEATURES: {overlap}"


def test_training_only_features_not_in_inference():
    from src.core.constants.feature_constants import INFERENCE_FEATURES, TRAINING_ONLY_FEATURES
    overlap = set(TRAINING_ONLY_FEATURES) & set(INFERENCE_FEATURES)
    assert not overlap, (
        f"TRAINING_ONLY_FEATURES must not appear in INFERENCE_FEATURES. Found: {overlap}"
    )


def test_all_inference_features_have_business_labels():
    from src.core.constants.feature_constants import INFERENCE_FEATURES, FEATURE_BUSINESS_LABELS
    missing = [f for f in INFERENCE_FEATURES if f not in FEATURE_BUSINESS_LABELS]
    assert not missing, f"Missing business labels for: {missing}"


def test_cold_start_reduced_features_subset_of_inference():
    from src.core.constants.feature_constants import COLD_START_REDUCED_FEATURES, INFERENCE_FEATURES
    extra = set(COLD_START_REDUCED_FEATURES) - set(INFERENCE_FEATURES)
    assert not extra, f"COLD_START_REDUCED_FEATURES not subset of INFERENCE_FEATURES: {extra}"


def test_quantile_level_derivation():
    from src.core.constants.model_constants import QUANTILE_PRODUCTION, ASYMMETRIC_ALPHA
    expected = ASYMMETRIC_ALPHA / (1 + ASYMMETRIC_ALPHA)
    assert abs(QUANTILE_PRODUCTION - expected) < 1e-6, (
        f"QUANTILE_PRODUCTION={QUANTILE_PRODUCTION} != ALPHA/(1+ALPHA)={expected}"
    )


def test_quantile_levels_all_contains_production():
    from src.core.constants.model_constants import QUANTILE_LEVELS_ALL, QUANTILE_PRODUCTION
    assert QUANTILE_PRODUCTION in QUANTILE_LEVELS_ALL


def test_best_iteration_in_valid_range():
    from src.core.constants.model_constants import BEST_ITERATION_PRODUCTION
    assert 400 <= BEST_ITERATION_PRODUCTION <= 900, (
        f"BEST_ITERATION_PRODUCTION={BEST_ITERATION_PRODUCTION} outside [400, 900]"
    )


def test_decision_weights_sum_to_one():
    from src.core.constants.decision_constants import DEFAULT_DECISION_WEIGHTS
    total = sum(DEFAULT_DECISION_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-6, (
        f"DEFAULT_DECISION_WEIGHTS sum={total:.6f}, must be 1.0"
    )


def test_decision_weights_all_components_present():
    from src.core.constants.decision_constants import DEFAULT_DECISION_WEIGHTS
    required = {"roi", "stock", "uncertainty", "substitution"}
    assert set(DEFAULT_DECISION_WEIGHTS.keys()) == required, (
        f"Missing weight keys: {required - set(DEFAULT_DECISION_WEIGHTS.keys())}"
    )


def test_approve_threshold_above_review_threshold():
    from src.core.constants.decision_constants import (
        DEFAULT_DECISION_APPROVE_THRESHOLD,
        DEFAULT_DECISION_REVIEW_THRESHOLD,
    )
    assert DEFAULT_DECISION_APPROVE_THRESHOLD > DEFAULT_DECISION_REVIEW_THRESHOLD, (
        "APPROVE_THRESHOLD must be strictly greater than REVIEW_THRESHOLD"
    )


def test_safety_bounds_cover_all_v2_weight_keys():
    from src.core.constants.business_constants import SAFETY_BOUNDS
    weight_keys = {
        "DECISION_WEIGHT_ROI", "DECISION_WEIGHT_STOCK",
        "DECISION_WEIGHT_UNCERTAINTY", "DECISION_WEIGHT_SUBSTITUTION",
    }
    missing = weight_keys - set(SAFETY_BOUNDS.keys())
    assert not missing, f"SAFETY_BOUNDS missing V2 weight keys: {missing}"


def test_cogs_scenarios_have_required_keys():
    from src.core.constants.decision_constants import COGS_SCENARIOS
    required = {"cogs_pct", "promo_fixed_cost", "holding_cost_day"}
    for name, scenario in COGS_SCENARIOS.items():
        missing = required - set(scenario.keys())
        assert not missing, f"COGS_SCENARIOS[{name}] missing keys: {missing}"
