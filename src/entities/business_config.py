"""Business configuration entity — Category 3 runtime parameter."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.core.constants.business_constants import SAFETY_BOUNDS


@dataclass
class BusinessConfig:
    """Runtime-configurable business parameter.

    Stored in business_configs DB table. Redis-cached (TTL=300s).
    Every change persists previous_value, updated_by, reason for audit.
    """
    config_key     : str
    config_value   : Any
    config_type    : str        # "float" | "int" | "str" | "json"
    updated_by     : str
    updated_at     : datetime
    reason         : str
    previous_value : Any = None

    def is_within_safe_bounds(self, key: str, value: float) -> bool:
        """Validate against hardcoded SAFETY_BOUNDS. Returns False if exceeded."""
        if key not in SAFETY_BOUNDS:
            return True   # key without bounds is always valid
        lo, hi = SAFETY_BOUNDS[key]
        return lo <= value <= hi
