"""jobpulse.validation.base — Base classes for validation rules."""

import abc
from dataclasses import dataclass

import pandas as pd

from jobpulse.validation.config import Severity


@dataclass
class RuleResult:
    """Stores the result of a validation rule execution."""

    rule_name: str
    severity: Severity
    rows_checked: int
    rows_failed: int
    execution_time: float
    failed_indices: list[int]
    error_message: str


class BaseValidationRule(abc.ABC):
    """Abstract base class for all validation rules."""

    @property
    @abc.abstractmethod
    def rule_name(self) -> str:
        """Name of the rule."""
        pass

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """Description of what the rule checks."""
        pass

    @property
    @abc.abstractmethod
    def severity(self) -> Severity:
        """Severity level if the rule fails."""
        pass

    @abc.abstractmethod
    def validate(self, df: pd.DataFrame) -> tuple[pd.Series, str]:
        """Validates the dataframe.

        Args:
            df: The dataframe to validate.

        Returns:
            A tuple of (boolean_mask_of_failed_rows, error_message).
            The mask is True where the row FAILED validation, False where it passed.
        """
        pass
