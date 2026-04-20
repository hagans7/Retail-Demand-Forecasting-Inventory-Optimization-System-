"""Service providers — composed with injected dependencies."""
from __future__ import annotations

from fastapi import Depends

from src.interfaces.base_config_repository import BaseConfigRepository
from src.interfaces.base_decision_repository import BaseDecisionRepository
from src.interfaces.base_elasticity_repository import BaseElasticityRepository
from src.interfaces.base_feature_repository import BaseFeatureRepository
from src.interfaces.base_forecast_repository import BaseForecastRepository
from src.interfaces.base_model_client import BaseModelClient
from src.interfaces.base_model_registry import BaseModelRegistry
from src.interfaces.base_storage_client import BaseStorageClient
from src.providers.infrastructure import (
    get_model_client,
    get_storage_client,
)
from src.providers.repositories import (
    get_config_repo,
    get_decision_repo,
    get_elasticity_repo,
    get_forecast_repo,
    get_monitoring_repo,
)


def _get_feature_repo(db=Depends(lambda: None)):
    # Resolved via repositories.py at runtime
    from src.providers.repositories import get_db_session  # noqa
    raise NotImplementedError("Use get_feature_repo from repositories")


def get_feature_repo(db=Depends(None)):
    from src.providers.infrastructure import get_db_session
    from src.repositories.feature_repository import FeatureRepository
    # Will be properly wired via Depends in route handlers
    pass


def get_model_registry_repo(db=Depends(None)):
    from src.repositories.model_registry_repository import ModelRegistryRepository
    pass


# ------------------------------------------------------------------
# Forecast service providers
# ------------------------------------------------------------------

def get_handle_cold_start_service(
    model_client: BaseModelClient = Depends(get_model_client),
    feature_repo: BaseFeatureRepository = Depends(get_feature_repo),
    model_registry: BaseModelRegistry = Depends(get_model_registry_repo),
):
    from src.services.handle_cold_start import HandleColdStartService
    return HandleColdStartService(
        model_client=model_client,
        feature_repo=feature_repo,
        model_registry=model_registry,
    )


def get_generate_forecast_service(
    model_client: BaseModelClient = Depends(get_model_client),
    feature_repo: BaseFeatureRepository = Depends(get_feature_repo),
    model_registry: BaseModelRegistry = Depends(get_model_registry_repo),
    forecast_repo: BaseForecastRepository = Depends(get_forecast_repo),
    config_repo: BaseConfigRepository = Depends(get_config_repo),
):
    from src.services.generate_forecast import GenerateForecastService
    from src.services.handle_cold_start import HandleColdStartService
    cold_start = HandleColdStartService(
        model_client=model_client,
        feature_repo=feature_repo,
        model_registry=model_registry,
    )
    return GenerateForecastService(
        model_client=model_client,
        feature_repo=feature_repo,
        model_registry=model_registry,
        forecast_repo=forecast_repo,
        cold_start_service=cold_start,
    )


def get_compute_replenishment_service(
    model_client: BaseModelClient = Depends(get_model_client),
    feature_repo: BaseFeatureRepository = Depends(get_feature_repo),
    model_registry: BaseModelRegistry = Depends(get_model_registry_repo),
    forecast_repo: BaseForecastRepository = Depends(get_forecast_repo),
    config_repo: BaseConfigRepository = Depends(get_config_repo),
):
    from src.services.compute_replenishment import ComputeReplenishmentService
    forecast_service = get_generate_forecast_service(
        model_client=model_client, feature_repo=feature_repo,
        model_registry=model_registry, forecast_repo=forecast_repo,
        config_repo=config_repo,
    )
    return ComputeReplenishmentService(
        forecast_service=forecast_service,
        config_repo=config_repo,
    )


# ------------------------------------------------------------------
# V2 Decision Intelligence service providers
# ------------------------------------------------------------------

def get_simulate_promo_roi_service(
    model_client: BaseModelClient = Depends(get_model_client),
    feature_repo: BaseFeatureRepository = Depends(get_feature_repo),
    model_registry: BaseModelRegistry = Depends(get_model_registry_repo),
    forecast_repo: BaseForecastRepository = Depends(get_forecast_repo),
    config_repo: BaseConfigRepository = Depends(get_config_repo),
    decision_repo: BaseDecisionRepository = Depends(get_decision_repo),
    elasticity_repo: BaseElasticityRepository = Depends(get_elasticity_repo),
):
    from src.services.simulate_promo_roi import SimulatePromoROIService
    from src.services.generate_forecast import GenerateForecastService
    from src.services.handle_cold_start import HandleColdStartService
    from src.services.simulate_promo_uplift import SimulatePromoUpliftService
    from src.services.compute_decision_uncertainty import ComputeDecisionUncertaintyService
    from src.services.simulate_cross_item_impact import SimulateCrossItemImpactService
    from src.services.compute_replenishment import ComputeReplenishmentService
    from src.services.compute_decision_score import ComputeDecisionScoreService

    cold_start = HandleColdStartService(model_client, feature_repo, model_registry)
    forecast_svc = GenerateForecastService(
        model_client, feature_repo, model_registry, forecast_repo, cold_start
    )
    uplift_svc    = SimulatePromoUpliftService(model_client, feature_repo, model_registry, elasticity_repo)
    uncertainty   = ComputeDecisionUncertaintyService()
    cross_item    = SimulateCrossItemImpactService()
    replenishment = ComputeReplenishmentService(forecast_svc, config_repo)
    score_svc     = ComputeDecisionScoreService(config_repo)

    return SimulatePromoROIService(
        forecast_service=forecast_svc,
        uplift_service=uplift_svc,
        uncertainty_service=uncertainty,
        cross_item_service=cross_item,
        replenishment_service=replenishment,
        score_service=score_svc,
        elasticity_repo=elasticity_repo,
        decision_repo=decision_repo,
        config_repo=config_repo,
    )
