"""jobpulse.validation.report — Validation report dataclasses."""

from dataclasses import dataclass, field
from datetime import datetime

from jobpulse.validation.base import RuleResult


@dataclass
class ValidationReport:
    """Aggregates the results of all validation checks."""

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    rows_checked: int = 0
    rows_valid: int = 0
    rows_warning: int = 0
    rows_invalid: int = 0
    critical_failures: int = 0

    duplicate_rows: int = 0
    duplicate_content: int = 0
    missing_required_fields: int = 0
    salary_errors: int = 0
    experience_errors: int = 0
    location_errors: int = 0
    schema_errors: int = 0
    contact_errors: int = 0
    currency_errors: int = 0
    company_errors: int = 0

    unknown_skills: list[str] = field(default_factory=list)
    rules_executed: int = 0
    execution_time: float = 0.0

    rule_results: list[RuleResult] = field(default_factory=list)

    @property
    def rows_per_second(self) -> float:
        return (
            self.rows_checked / self.execution_time if self.execution_time > 0 else 0.0
        )

    @property
    def success_rate(self) -> float:
        return self.rows_valid / self.rows_checked if self.rows_checked > 0 else 0.0
