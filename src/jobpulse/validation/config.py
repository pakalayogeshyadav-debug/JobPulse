"""jobpulse.validation.config — Configuration settings for the validation layer."""

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["INFO", "WARNING", "ERROR", "CRITICAL"]


@dataclass
class RuleConfig:
    severity: Severity = "ERROR"
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationConfig:
    """Configures the severity and parameters for various validation rules."""

    required_fields: RuleConfig = field(
        default_factory=lambda: RuleConfig(severity="ERROR")
    )
    salary_validation: RuleConfig = field(
        default_factory=lambda: RuleConfig(
            severity="WARNING", parameters={"max_salary": 2000000}
        )
    )
    duplicate_validation: RuleConfig = field(
        default_factory=lambda: RuleConfig(severity="ERROR")
    )
    future_dates: RuleConfig = field(
        default_factory=lambda: RuleConfig(severity="CRITICAL")
    )
    schema_validation: RuleConfig = field(
        default_factory=lambda: RuleConfig(severity="CRITICAL")
    )
    experience_validation: RuleConfig = field(
        default_factory=lambda: RuleConfig(severity="WARNING")
    )
    location_validation: RuleConfig = field(
        default_factory=lambda: RuleConfig(severity="WARNING")
    )
    contact_validation: RuleConfig = field(
        default_factory=lambda: RuleConfig(severity="WARNING")
    )
    content_hash: RuleConfig = field(
        default_factory=lambda: RuleConfig(severity="WARNING")
    )
    currency_validation: RuleConfig = field(
        default_factory=lambda: RuleConfig(severity="WARNING")
    )
    company_validation: RuleConfig = field(
        default_factory=lambda: RuleConfig(severity="WARNING")
    )


# Singleton configuration instance
VALIDATION_CONFIG = ValidationConfig()
