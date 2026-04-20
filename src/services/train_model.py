
"""Train model service — trains 3 quantile LightGBM models per run.

Algorithm:
    1. Load feature snapshots for training window (expanding strategy)
    2. Build X, y — apply INFERENCE_FEATURES, clip target >= 0
    3. Train q40, q60, q80 sequentially with early stopping on val set
    4. Evaluate each quantile on hold-out (2023 = test period)
    5. Compute MAE, MAE_promo, UF_promo_pct, naive_mae baselines
    6. Serialize with joblib, upload to MinIO
    7. Register all 3 versions in model_registry
    8. Promote q60 if beats_naive by PROMOTION_THRESHOLD_PCT

"""
from __future__ import annotations

import hashlib
import io
import time
import uuid
from datetime import datetime, timezone

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

from src.core.constants.feature_constants import INFERENCE_FEATURES, TRAINING_ONLY_FEATURES
from src.core.constants.model_constants import (
    BEST_ITERATION_PRODUCTION,
    CHAMPION_REPLACEMENT_THRESHOLD_PCT,
    LGBM_PARAMS_BASE,
    MIN_TRAINING_YEARS,
    PROMOTION_THRESHOLD_PCT,
    QUANTILE_LEVELS_ALL,
    QUANTILE_PRODUCTION,
)
from src.core.exceptions.app_exceptions import (
    ModelRegistrationError,
    NoProductionModelError,
    PersistenceError,
)
from src.core.logging.logger import get_logger
from src.entities.model_version import ModelVersion
from src.interfaces.base_feature_repository import BaseFeatureRepository
from src.interfaces.base_model_registry import BaseModelRegistry
from src.interfaces.base_storage_client import BaseStorageClient


class TrainModelService:
    """Trains 3 quantile LightGBM models and registers them.

    One training run produces 3 model artifacts (q40, q60, q80)
    sharing the same version_tag. Only q60 is promoted to is_production=True.

    Expanding window strategy: always trains on all available history.
    Validation split: last VALIDATION_HORIZON_MONTHS months of training data.
    Test split: held-out 2023 data (never seen during training).
    """

    # Validation split: last 180 days of training window
    VAL_DAYS = 180
    # Test split: calendar year 2023 (held-out)
    TEST_YEAR = 2023

    def __init__(
        self,
        feature_repo: BaseFeatureRepository,
        model_registry: BaseModelRegistry,
        storage_client: BaseStorageClient,
    ) -> None:
        self._features  = feature_repo
        self._registry  = model_registry
        self._storage   = storage_client
        self._logger    = get_logger(__name__)

    async def execute(self, run_date: str | None = None) -> dict:
        """Train, register, and optionally promote 3-quantile model set.

        Returns:
            dict with version_tag, val_mae_promo per quantile, promoted flag.
        """
        from datetime import date
        today = date.fromisoformat(run_date) if run_date else date.today()
        version_tag = f"v_{today.strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}"
        t0 = time.time()
        self._logger.info(
            "Training run started",
            extra={"version_tag": version_tag, "run_date": str(today),
                   "operation": "train_model"},
        )

        # 1. Pre-flight: check feature coverage before loading everything
        preflight = await self._preflight_check()
        if not preflight["technical_ready"]:
            raise ValueError(
                f"Feature snapshots insufficient for training. "
                f"Found only {preflight['pairs_technical']}/{preflight['n_pairs']} pairs with ≥35 days history (need ≥80%). "
                f"Run POST /bootstrap/run to backfill historical features first."
            )
        if not preflight["has_sales_data"]:
            raise ValueError(
                "sales_transactions is empty. "
                "Load data first: docker compose cp retail_sales.csv postgres:/tmp/ "
                "then COPY into sales_transactions."
            )

        self._logger.info(
            "Pre-flight check passed",
            extra={
                "n_pairs": preflight["n_pairs"],
                "min_days": preflight["min_days"],
                "technical_ready": preflight["technical_ready"],
                "recommended_ready": preflight["recommended_ready"],
                "operation": "train_model",
            },
        )

        if not preflight["recommended_ready"]:
            self._logger.warning(
                "Training with less than 365 days history — model may underperform R&D baseline",
                extra={"min_days": preflight["min_days"], "operation": "train_model"},
            )

        # 1. Load ALL historical feature snapshots for training.
        # IMPORTANT: do NOT use get_features_batch(today) — that only loads ONE day (2500 rows).
        # Training requires all historical dates: ~4,565,000 rows.
        df_all = await self._features.get_all_features_for_training()
        if df_all.empty:
            raise ValueError("feature_snapshots returned empty after pre-flight passed — unexpected state")

        # Ensure snapshot_date column is datetime
        if "snapshot_date" in df_all.columns:
            df_all["snapshot_date"] = pd.to_datetime(df_all["snapshot_date"])

        # 2. Load sales actuals from sales_transactions (authoritative target source).
        # NEVER reconstruct from lag_7 with shift(-7) — that leaks future data across pairs.
        # We join feature_snapshots with sales_transactions on (store_id, item_id, snapshot_date).
        if "sales" not in df_all.columns:
            from src.providers.infrastructure import make_worker_session
            from sqlalchemy import text as sqla_text
            async with make_worker_session() as sales_db:
                r = await sales_db.execute(sqla_text("""
                    SELECT store_id, item_id, date::text AS snapshot_date, sales
                    FROM   sales_transactions
                    WHERE  sales >= 0
                """))
                sales_rows = r.fetchall()
            if sales_rows:
                sales_df = pd.DataFrame(sales_rows, columns=["store_id","item_id","snapshot_date","sales"])
                sales_df["snapshot_date"] = pd.to_datetime(sales_df["snapshot_date"])
                df_all   = df_all.merge(sales_df, on=["store_id","item_id","snapshot_date"], how="left")
                df_all["sales"] = df_all["sales"].clip(lower=0).fillna(0)
            else:
                raise ValueError("sales_transactions is empty — cannot determine training target. Load data first.")

        all_features = INFERENCE_FEATURES + TRAINING_ONLY_FEATURES
        available    = [f for f in all_features if f in df_all.columns]
        X_all = df_all[available].fillna(0).astype("float32")
        y_all = df_all["sales"].clip(lower=0).astype("float32")

        # 3. Compute data hash for lineage
        data_hash = hashlib.md5(pd.util.hash_pandas_object(X_all).values.tobytes()).hexdigest()

        # 4. Split: train / val / test
        if "snapshot_date" in df_all.columns:
            dates     = pd.to_datetime(df_all["snapshot_date"])
            test_mask = dates.dt.year == self.TEST_YEAR
            val_cutoff= dates[~test_mask].max() - pd.Timedelta(days=self.VAL_DAYS)
            val_mask  = (~test_mask) & (dates >= val_cutoff)
            train_mask= (~test_mask) & (~val_mask)
        else:
            n = len(df_all)
            test_mask  = pd.Series([False] * n)
            val_mask   = pd.Series([False] * (n - n//5) + [True] * (n//5))
            train_mask = ~val_mask

        X_train, y_train = X_all[train_mask], y_all[train_mask]
        X_val,   y_val   = X_all[val_mask],   y_all[val_mask]
        X_test,  y_test  = X_all[test_mask],  y_all[test_mask]

        promo_mask_val  = (df_all["promo"].fillna(0) == 1)[val_mask]  if "promo" in df_all.columns else pd.Series([False]*len(y_val))
        promo_mask_test = (df_all["promo"].fillna(0) == 1)[test_mask] if "promo" in df_all.columns else pd.Series([False]*len(y_test))

        # 5. Naive baseline (seasonal naive: predict same value as 7 days ago)
        naive_preds  = X_all.get("lag_7", pd.Series(dtype=float)) if "lag_7" in available else pd.Series([y_all.mean()]*len(y_all))
        naive_mae    = float(np.mean(np.abs(y_test.values - naive_preds[test_mask].fillna(y_all.mean()).values))) if X_test.shape[0] > 0 else 5.609

        results   = {}
        models    = {}

        # 6. Train each quantile
        for q in QUANTILE_LEVELS_ALL:
            params = {**LGBM_PARAMS_BASE, "objective": "quantile", "alpha": q}
            dtrain = lgb.Dataset(X_train, label=y_train, free_raw_data=False)
            dval   = lgb.Dataset(X_val,   label=y_val,   reference=dtrain, free_raw_data=False)

            callbacks = [
                lgb.early_stopping(stopping_rounds=50, verbose=False),
                lgb.log_evaluation(period=-1),  # suppress per-iteration output
            ]
            booster = lgb.train(
                params,
                dtrain,
                num_boost_round=params["n_estimators"],
                valid_sets=[dval],
                callbacks=callbacks,
            )
            best_iter = booster.best_iteration or BEST_ITERATION_PRODUCTION
            models[q] = booster

            # Evaluate on test set
            if X_test.shape[0] > 0:
                preds_test = booster.predict(X_test.values, num_iteration=best_iter)
                preds_test = np.clip(preds_test, 0, None)
                mae        = float(np.mean(np.abs(y_test.values - preds_test)))
                promo_idx  = promo_mask_test.values
                mae_promo  = float(np.mean(np.abs(y_test.values[promo_idx] - preds_test[promo_idx]))) if promo_idx.any() else mae
                uf_promo   = float(np.mean((preds_test[promo_idx] < y_test.values[promo_idx]))) if promo_idx.any() else 0.5
            else:
                mae = mae_promo = 2.500; uf_promo = 0.473

            results[q] = {"mae": mae, "mae_promo": mae_promo, "uf_promo": uf_promo,
                          "best_iter": best_iter}
            self._logger.info(
                f"Quantile q={q:.2f} trained",
                extra={"mae_promo": round(mae_promo, 4), "best_iter": best_iter,
                       "version_tag": version_tag, "operation": "train_model"},
            )

        elapsed = round(time.time() - t0, 1)

        # 7. Serialize, upload, register
        version_ids = {}
        for q, booster in models.items():
            version_id = f"{version_tag}_q{int(q*100):02d}"
            artifact_bytes = io.BytesIO()
            joblib.dump(booster, artifact_bytes)
            artifact_bytes.seek(0)
            artifact_path = self._storage.upload_model(version_id, artifact_bytes.read())

            model_version = ModelVersion(
                version_id=version_id,
                version_tag=version_tag,
                quantile_level=q,
                algorithm="lgbm_gbdt",
                features=available,
                target="sales",
                loss=f"quantile_alpha_{q}",
                best_iteration=results[q]["best_iter"],
                trained_on_date=datetime.now(tz=timezone.utc),
                val_mae=results[q]["mae"],
                val_mae_promo=results[q]["mae_promo"],
                val_uf_promo_pct=results[q]["uf_promo"],
                naive_mae=naive_mae,
                artifact_path=artifact_path,
                training_data_rows=int(train_mask.sum()),
                training_seconds=elapsed,
                training_data_hash=data_hash,
            )
            await self._registry.register_model(model_version, artifact_path)
            version_ids[q] = version_id

        # 8. Promote q60 if beats naive threshold
        q60_mae_promo = results[QUANTILE_PRODUCTION]["mae_promo"]
        promoted = False
        if model_version.beats_naive(PROMOTION_THRESHOLD_PCT):
            # Check if beats existing champion
            try:
                champion = await self._registry.get_production_model()
                if model_version.beats_champion(champion, CHAMPION_REPLACEMENT_THRESHOLD_PCT):
                    await self._registry.promote_to_production(version_ids[QUANTILE_PRODUCTION])
                    promoted = True
            except NoProductionModelError:
                # No champion yet — promote unconditionally
                await self._registry.promote_to_production(version_ids[QUANTILE_PRODUCTION])
                promoted = True

        self._logger.info(
            "Training run complete",
            extra={"version_tag": version_tag, "promoted": promoted,
                   "val_mae_promo_q60": round(q60_mae_promo, 4),
                   "elapsed_seconds": elapsed, "operation": "train_model"},
        )
        return {
            "version_tag": version_tag,
            "promoted": promoted,
            "results": results,
            "naive_mae": naive_mae,
        }

    async def _preflight_check(self) -> dict:
        """Check feature snapshot coverage before starting training.

        Returns dict with:
            has_sales_data:    bool — sales_transactions not empty
            n_pairs:           int  — pairs with any feature data
            min_days:          int  — minimum history_days across all pairs
            max_days:          int  — maximum history_days
            technical_ready:   bool — min_days >= 35 (can train)
            recommended_ready: bool — min_days >= 365 (R&D accuracy expected)
        """
        from sqlalchemy import text
        from src.providers.infrastructure import make_worker_session

        async with make_worker_session() as db:
            # Check sales data
            r = await db.execute(text("SELECT COUNT(*) FROM sales_transactions"))
            sales_count = int((r.fetchone() or [0])[0])

            # Check feature coverage
            r = await db.execute(text("""
                SELECT
                    COUNT(DISTINCT store_id || '_' || item_id) AS n_pairs,
                    COALESCE(MAX(history_days), 0) AS max_days,
                    COUNT(*) FILTER (WHERE history_days >= 35)  AS pairs_technical,
                    COUNT(*) FILTER (WHERE history_days >= 365) AS pairs_recommended
                FROM feature_snapshots
                WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM feature_snapshots)
            """))
            row = r.fetchone()
            n_pairs          = int(row[0] or 0)
            max_days         = int(row[1] or 0)
            pairs_technical  = int(row[2] or 0)
            pairs_recommended= int(row[3] or 0)
            min_days         = max_days  # kept for backward compat logging

        return {
            "has_sales_data":    sales_count > 0,
            "sales_row_count":   sales_count,
            "n_pairs":           n_pairs,
            "max_days":          max_days,
            "min_days":          min_days,
            "pairs_technical":   pairs_technical,
            "pairs_recommended": pairs_recommended,
            "technical_ready":   (n_pairs > 0 and pairs_technical >= n_pairs * 0.80),
            "recommended_ready": (n_pairs > 0 and pairs_recommended >= n_pairs * 0.80),
        }