"""jobpulse.validation.exceptions — Custom exceptions for the validation layer."""


class ValidationWarning(Warning):
    """Raised for non-critical validation issues."""

    pass


class DataValidationError(Exception):
    """Base exception for validation errors."""

    pass


class CriticalValidationError(DataValidationError):
    """Raised when a validation failure is critical and must stop the pipeline."""

    pass
