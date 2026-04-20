"""Cross-item impact entity — cannibalization and halo effects."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ItemRelationship(str, Enum):
    SUBSTITUTE    = "SUBSTITUTE"     # negative correlation → cannibalization
    COMPLEMENTARY = "COMPLEMENTARY"  # positive correlation → halo
    INDEPENDENT   = "INDEPENDENT"    # near-zero correlation → no adjustment


@dataclass
class CrossItemImpact:
    """Estimated basket-level revenue impact when a promo activates on source_item.

    cannibalization_penalty_pct is the primary metric for ROI adjustment in
    SimulatePromoROIService. It represents lost basket revenue from substitution.

    Known limitation: correlation ≠ causation. Dampening factors (0.5 substitute,
    0.3 complementary) are conservative estimates from domain knowledge.
    """
    source_item                  : str
    impacted_items               : list[dict] = field(default_factory=list)
    # Each dict: {item_id, relationship, correlation, impact_pct}
    total_substitution_loss_pct  : float = 0.0
    total_halo_gain_pct          : float = 0.0
    net_basket_impact_pct        : float = 0.0   # halo - substitution
    cannibalization_penalty_pct  : float = 0.0   # = substitution_loss
    n_substitutes                : int = 0
    n_complements                : int = 0

    def has_significant_cannibalization(self) -> bool:
        return self.cannibalization_penalty_pct > 5.0

    def net_basket_positive(self) -> bool:
        return self.net_basket_impact_pct > 0

    def risk_note(self) -> str | None:
        if self.has_significant_cannibalization():
            return (
                f"Promo may reduce basket revenue by "
                f"{self.cannibalization_penalty_pct:.1f}% due to substitution effects."
            )
        return None
