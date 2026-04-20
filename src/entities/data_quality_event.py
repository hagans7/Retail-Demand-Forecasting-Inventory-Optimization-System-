"""Data quality gate entities."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DataQualityCheck:
    """Result of a single data quality check."""
    check_name: str
    passed    : bool
    severity  : str    # "CRITICAL" | "WARNING" | "INFO"
    details   : str = ""


@dataclass
class DataQualityEvent:
    """Aggregate result of all pre-flight checks for a pipeline run.

    pipeline_blocked=True means downstream pipelines must not run.
    fallback_strategy describes what the system does when blocked.
    """
    run_id              : str
    run_date            : object   # date
    checks              : list[DataQualityCheck] = field(default_factory=list)
    all_critical_passed : bool = True
    pipeline_blocked    : bool = False
    fallback_strategy   : str = "NONE"

    def critical_failures(self) -> list[DataQualityCheck]:
        return [c for c in self.checks if not c.passed and c.severity == "CRITICAL"]

    def should_block_pipeline(self) -> bool:
        return not self.all_critical_passed

    def warning_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed and c.severity == "WARNING")
