"""Get forecast confidence service — three-quantile prediction bands."""
from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from src.core.constants.feature_constants import INFERENCE_FEATURES
from src.core.constants.model_constants import BEST_ITERATION_PRODUCTION, QUANTILE_LEVELS_ALL
from src.core.logging.logger import get_logger
from src.entities.forecast_confidence import DailyConfidenceBand, ForecastConfidence
from src.interfaces.base_feature_repository import BaseFeatureRepository
from src.interfaces.base_model_client import BaseModelClient
from src.interfaces.base_model_registry import BaseModelRegistry


class GetForecastConfidenceService:
    """Loads all 3 quantile models and produces per-day confidence bands.

    Requires all 3 artifacts (q40, q60, q80) to be registered under
    the same version_tag as the production model.
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
        target_dates: list[date],
        promo_plan: list[int],
        price_plan: list[float],
    ) -> ForecastConfidence:
        prod = await self._registry.get_production_model()
        version_tag = prod.version_tag

        # Load feature matrix
        rows = []
        for d, promo in zip(target_dates, promo_plan):
            df = await self._features.get_features_for_date(store_id, item_id, d)
            row = df if df is not None else pd.DataFrame([{f: 0.0 for f in INFERENCE_FEATURES}])
            row = row.reindex(columns=INFERENCE_FEATURES, fill_value=0.0)
            if "promo" in row.columns:
                row["promo"] = promo
            rows.append(row)
        X = pd.concat(rows, ignore_index=True).fillna(0.0).astype("float32")

        # Predict each quantile
        preds_per_q: dict[float, np.ndarray] = {}
        for q in QUANTILE_LEVELS_ALL:
            try:
                qmodel = await self._registry.get_model_by_quantile(version_tag, q)
                self._model.load_model(qmodel.version_id, quantile_level=q)
                raw = self._model.predict(X, num_iteration=BEST_ITERATION_PRODUCTION)
                preds_per_q[q] = np.clip(raw, 0, None)
            except Exception as e:
                self._logger.warning(
                    f"Could not load q={q} model — using q60 as fallback",
                    extra={"version_tag": version_tag, "error": str(e)},
                )
                preds_per_q[q] = preds_per_q.get(0.60, np.zeros(len(target_dates)))

        bands = []
        for i, d in enumerate(target_dates):
            lo = float(preds_per_q.get(0.40, preds_per_q.get(0.60, np.zeros(1)))[i])
            mi = float(preds_per_q.get(0.60, preds_per_q.get(0.40, np.zeros(1)))[i])
            hi = float(preds_per_q.get(0.80, preds_per_q.get(0.60, np.zeros(1)))[i])
            width = (hi - lo) / max(mi, 0.01)
            label = "NARROW" if width < 0.3 else ("WIDE" if width > 0.8 else "MODERATE")
            bands.append(DailyConfidenceBand(
                date=d, lower_bound=round(lo,2), central=round(mi,2),
                upper_bound=round(hi,2), uncertainty_width=round(width,3),
                uncertainty_label=label,
            ))

        return ForecastConfidence(
            store_id=store_id, item_id=item_id,
            version_tag=version_tag, daily_bands=bands,
        )
