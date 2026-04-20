"""Explain forecast service — SHAP-based driver translation to business language."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import shap

from src.core.constants.feature_constants import FEATURE_BUSINESS_LABELS, INFERENCE_FEATURES, TOP_GAIN_FEATURES_FOR_SNAPSHOT
from src.core.constants.model_constants import BEST_ITERATION_PRODUCTION, TRAINING_MEAN_SALES
from src.core.logging.logger import get_logger
from src.entities.forecast_explanation import FeatureDriver, ForecastExplanation
from src.interfaces.base_feature_repository import BaseFeatureRepository
from src.interfaces.base_model_client import BaseModelClient
from src.interfaces.base_model_registry import BaseModelRegistry


class ExplainForecastService:
    """Generates SHAP-based forecast explanations in business language.

    Uses TreeExplainer on the production q60 LightGBM model.
    Returns top positive and negative feature drivers per prediction day.
    """

    def __init__(
        self,
        model_client: BaseModelClient,
        feature_repo: BaseFeatureRepository,
        model_registry: BaseModelRegistry,
    ) -> None:
        self._model    = model_client
        self._features = feature_repo
        self._registry = model_registry
        self._logger   = get_logger(__name__)

    async def execute(
        self,
        store_id: str,
        item_id: str,
        target_date: date,
        promo: int = 0,
        price: float = 20.0,
    ) -> ForecastExplanation:
        prod_model   = await self._registry.get_production_model()
        self._model.load_model(prod_model.version_id, quantile_level=0.60)
        feature_df   = await self._feature_row(store_id, item_id, target_date, promo)

        # SHAP values — TreeExplainer is the correct explainer for LightGBM
        try:
            booster = self._model._booster   # access underlying booster
            explainer = shap.TreeExplainer(booster)
            shap_values = explainer.shap_values(feature_df.values)
            base_value  = float(explainer.expected_value)
        except Exception as e:
            self._logger.warning(
                "SHAP explanation failed — returning snapshot-based explanation",
                extra={"store_id": store_id, "item_id": item_id,
                       "error": str(e), "operation": "explain_forecast"},
            )
            shap_values = np.zeros((1, len(INFERENCE_FEATURES)))
            base_value  = float(TRAINING_MEAN_SALES)

        # Map SHAP values to business labels
        shap_row = shap_values[0]
        drivers  = []
        for i, feat in enumerate(feature_df.columns):
            impact = float(shap_row[i])
            if abs(impact) < 0.01:
                continue
            label = FEATURE_BUSINESS_LABELS.get(feat, feat)
            drivers.append(FeatureDriver(
                label=label,
                feature_name=feat,
                impact=round(impact, 3),
                direction="positive" if impact > 0 else "negative",
            ))
        drivers.sort(key=lambda d: abs(d.impact), reverse=True)

        preds       = self._model.predict(feature_df, num_iteration=BEST_ITERATION_PRODUCTION)
        final_pred  = max(0.0, float(preds[0]))

        self._logger.info(
            "Forecast explanation generated",
            extra={"store_id": store_id, "item_id": item_id,
                   "n_drivers": len(drivers), "operation": "explain_forecast"},
        )
        return ForecastExplanation(
            store_id=store_id, item_id=item_id,
            target_date=target_date,
            base_value=round(base_value, 2),
            drivers=drivers,
            final_forecast=round(final_pred, 2),
        )

    async def _feature_row(self, store_id, item_id, target_date, promo) -> pd.DataFrame:
        df = await self._features.get_features_for_date(store_id, item_id, target_date)
        if df is None:
            df = pd.DataFrame([{f: 0.0 for f in INFERENCE_FEATURES}])
        df = df.reindex(columns=INFERENCE_FEATURES, fill_value=0.0)
        if "promo" in df.columns:
            df["promo"] = promo
        return df.fillna(0.0).astype("float32")
