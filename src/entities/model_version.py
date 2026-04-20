"""Model version entity."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class ModelVersion:
    """Registered model version with full lineage metadata.

    Three versions are registered per training run (q40, q60, q80).
    Only q60 is promoted to is_production=True as primary.
    """
    version_id           : str
    version_tag          : str        # shared across q40/q60/q80 of same run
    quantile_level       : float      # 0.40 | 0.60 | 0.80
    algorithm            : str
    features             : list[str]
    target               : str
    loss                 : str
    best_iteration       : int
    trained_on_date      : datetime
    val_mae              : float
    val_mae_promo        : float
    val_uf_promo_pct     : float
    naive_mae            : float
    artifact_path        : str | None  # None if archived
    is_production        : bool = False
    promoted_at          : datetime | None = None
    training_data_start  : date | None = None
    training_data_end    : date | None = None
    training_data_rows   : int = 0
    training_seconds     : float = 0.0
    training_data_hash   : str | None = None
    archived             : bool = False
    archived_at          : datetime | None = None

    def beats_naive(self, threshold_pct: float = 30.0) -> bool:
        """True if model beats naive MAE_promo by threshold_pct."""
        improvement = (self.naive_mae - self.val_mae_promo) / self.naive_mae * 100
        return improvement >= threshold_pct

    def beats_champion(self, champion: "ModelVersion", threshold_pct: float = 3.0) -> bool:
        """True if this model beats champion MAE_promo by threshold_pct."""
        improvement = (champion.val_mae_promo - self.val_mae_promo) / champion.val_mae_promo * 100
        return improvement >= threshold_pct

    def is_primary_production(self) -> bool:
        """True only for the q60 production model."""
        return self.is_production and abs(self.quantile_level - 0.60) < 1e-6
