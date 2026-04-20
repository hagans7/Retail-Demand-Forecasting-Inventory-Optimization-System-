"""Providers — single import entry point for all route handlers.

Route handlers import ONLY from here, never from sub-modules directly.
"""
from src.providers.infrastructure import (
    get_db_session,
    get_model_client,
    get_redis_client,
    get_storage_client,
)
from src.providers.repositories import (
    get_config_repo,
    get_decision_repo,
    get_elasticity_repo,
    get_forecast_repo,
    get_monitoring_repo,
)
from src.providers.services import (
    get_compute_replenishment_service,
    get_generate_forecast_service,
    get_simulate_promo_roi_service,
)

__all__ = [
    "get_db_session",
    "get_model_client",
    "get_redis_client",
    "get_storage_client",
    "get_config_repo",
    "get_decision_repo",
    "get_elasticity_repo",
    "get_forecast_repo",
    "get_monitoring_repo",
    "get_generate_forecast_service",
    "get_compute_replenishment_service",
    "get_simulate_promo_roi_service",
]
