"""
Application exception hierarchy.

All typed exceptions raised within the platform inherit from AppBaseError.
Never raise bare Exception("message") anywhere in the codebase.

Exception routing:
    Client layer    → normalizes SDK errors → raises typed app exceptions
    Service layer   → decides criticality → propagates or degrades
    API layer       → catches typed exceptions → converts to HTTPException
"""
from __future__ import annotations


class AppBaseError(Exception):
    """Root of all application exceptions."""


# ---------------------------------------------------------------------------
# Feature store errors
# ---------------------------------------------------------------------------


class FeatureStoreError(AppBaseError):
    """Base for all feature store related errors."""


class FeatureStoreUnavailableError(FeatureStoreError):
    """Feature store connection unavailable. Critical — propagates to API 503."""


class FeaturesNotComputedError(FeatureStoreError):
    """Features not yet computed for this store-item-date.
    Non-critical: triggers cold start routing, not an error state."""


# ---------------------------------------------------------------------------
# Model errors
# ---------------------------------------------------------------------------


class ModelError(AppBaseError):
    """Base for all model-related errors."""


class ModelNotLoadedError(ModelError):
    """Model artifact not loaded in client. Critical — propagates to API 503."""


class NoProductionModelError(ModelError):
    """No model with is_production=True in registry. Critical — API 503."""


class ModelNotFoundError(ModelError):
    """Specific model version_id not found in registry."""


class PredictionError(ModelError):
    """Model inference failed after MAX_RETRIES. Critical — propagates to API 503."""


# ---------------------------------------------------------------------------
# Registry errors
# ---------------------------------------------------------------------------


class RegistryError(AppBaseError):
    """Base for model registry errors."""


class ModelRegistrationError(RegistryError):
    """Failed to register model version in registry."""


# ---------------------------------------------------------------------------
# Data errors
# ---------------------------------------------------------------------------


class DataError(AppBaseError):
    """Base for data-related errors."""


class DataFreshnessError(DataError):
    """Data is stale beyond DATA_FRESHNESS_HOURS_MAX threshold."""


class SchemaViolationError(DataError):
    """Incoming data does not match expected schema."""


class DataQualityGateFailedError(DataError):
    """Pre-flight data quality check failed a CRITICAL check.
    Pipeline is blocked; fallback strategy applies."""


# ---------------------------------------------------------------------------
# Cold start errors
# ---------------------------------------------------------------------------


class ColdStartError(AppBaseError):
    """Base for cold start related errors."""


class InsufficientHistoryError(ColdStartError):
    """Pair has insufficient history even for cold start (day 0)."""


# ---------------------------------------------------------------------------
# Decision intelligence errors (V2)
# ---------------------------------------------------------------------------


class DecisionError(AppBaseError):
    """Base for V2 decision layer errors."""


class SimulationNotFoundError(DecisionError):
    """Simulation with given simulation_id not found in decision_simulations."""


class COGSAssumptionMissingError(DecisionError):
    """Item not found in item_financial_assumptions and no __default__ row.
    Non-critical: service degrades to NORMAL_MARGIN scenario with Risk Note."""


class ElasticityDataUnavailableError(DecisionError):
    """No elasticity data for this item (neither observed nor initial estimate).
    Non-critical: service falls back to global baseline uplift."""


class DecisionScoreComputationError(DecisionError):
    """Weighted score computation failed.
    Non-critical: component set to 0.5 (neutral) with Risk Note."""


# ---------------------------------------------------------------------------
# Feedback errors
# ---------------------------------------------------------------------------


class FeedbackError(AppBaseError):
    """Base for feedback recalibration errors."""


class SimulationUnresolvableError(FeedbackError):
    """Simulation cannot be resolved — promo not executed in store (promo=0
    in actuals). Record is marked CANCELLED_IN_STORE; elasticity not updated."""


# ---------------------------------------------------------------------------
# Persistence / infrastructure errors
# ---------------------------------------------------------------------------


class PersistenceError(AppBaseError):
    """Database write or read failed. Critical — propagates to API 503."""


class CacheError(AppBaseError):
    """Redis cache operation failed.
    Non-critical — service degrades gracefully (skips cache)."""


class StorageError(AppBaseError):
    """MinIO artifact storage operation failed. Critical for model loading."""


class ConfigError(AppBaseError):
    """Base for configuration errors."""


class ConfigSafetyBoundsViolationError(ConfigError):
    """Attempted to set a value outside the hardcoded SAFETY_BOUNDS.
    Raises HTTP 422 at API layer."""
