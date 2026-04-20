# """Abstract base for feature repository."""
# from __future__ import annotations

# from abc import ABC, abstractmethod
# from datetime import date

# import pandas as pd


# class BaseFeatureRepository(ABC):
#     """Contract for reading from the feature_snapshots table.

#     Two access patterns:
#         1. Single pair + single date (on-demand API calls)
#         2. Full date batch (nightly batch inference)
#     """

#     @abstractmethod
#     async def get_features_for_date(
#         self,
#         store_id: str,
#         item_id: str,
#         target_date: date,
#     ) -> pd.DataFrame | None:
#         """Return feature row for a specific store-item-date.

#         Returns:
#             Single-row DataFrame with INFERENCE_FEATURES columns.
#             None if features not yet computed for that date (triggers cold start).

#         Raises:
#             FeatureStoreUnavailableError: On DB connection failure.
#         """

#     @abstractmethod
#     async def get_features_batch(self, target_date: date) -> pd.DataFrame:
#         """Return all store-item feature rows for a given date.

#         Used by batch_inference_pipeline only.
#         Returns DataFrame with 2500 rows × INFERENCE_FEATURES columns.

#         Raises:
#             FeatureStoreUnavailableError: On DB connection failure.
#         """

#     @abstractmethod
#     async def get_history_days(self, store_id: str, item_id: str) -> int:
#         """Count of days with available feature data for this pair.

#         Used by generate_forecast to determine cold start tier routing.
#         Returns 0 for brand-new pairs with no history.

#         Raises:
#             FeatureStoreUnavailableError: On DB connection failure.
#         """

"""Abstract base for feature repository."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


class BaseFeatureRepository(ABC):
    """Contract for reading from the feature_snapshots table.

    Two access patterns:
        1. Single pair + single date (on-demand API calls)
        2. Full date batch (nightly batch inference)
    """

    @abstractmethod
    async def get_features_for_date(
        self,
        store_id: str,
        item_id: str,
        target_date: date,
    ) -> pd.DataFrame | None:
        """Return feature row for a specific store-item-date.

        Returns:
            Single-row DataFrame with INFERENCE_FEATURES columns.
            None if features not yet computed for that date (triggers cold start).

        Raises:
            FeatureStoreUnavailableError: On DB connection failure.
        """

    @abstractmethod
    async def get_features_batch(self, target_date: date) -> pd.DataFrame:
        """Return all store-item feature rows for a given date (batch inference).

        Used by batch_inference_pipeline only.
        Returns DataFrame with 2500 rows × INFERENCE_FEATURES columns.

        Raises:
            FeatureStoreUnavailableError: On DB connection failure.
        """

    @abstractmethod
    async def get_all_features_for_training(self) -> pd.DataFrame:
        """Return ALL historical feature rows for model training.

        Returns DataFrame with ~4,565,000 rows (all pairs × all dates).
        Training needs full history — not just today's snapshot.

        Raises:
            FeatureStoreUnavailableError: On DB connection failure.
        """

    @abstractmethod
    async def get_history_days(self, store_id: str, item_id: str) -> int:
        """Count of days with available feature data for this pair.

        Used by generate_forecast to determine cold start tier routing.
        Returns 0 for brand-new pairs with no history.

        Raises:
            FeatureStoreUnavailableError: On DB connection failure.
        """