"""jobpulse.exceptions — Custom exception hierarchy for JobPulse ETL."""

from __future__ import annotations


class JobPulseError(Exception):
    """Base exception for all JobPulse errors."""

    def __init__(self, message: str, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause


class PipelineFatalError(JobPulseError):
    """Raised for unrecoverable pipeline errors that must abort execution."""
    pass


class ReportingError(JobPulseError):
    """Raised when report generation fails, but should not abort execution."""
    pass


class DatabaseError(JobPulseError):
    """Raised for general database errors."""
    pass


class DatabaseConnectionError(DatabaseError):
    """Raised when the database connection fails."""
    pass


class ForeignKeyError(DatabaseError):
    """Raised on foreign key constraint violations."""
    pass


class DuplicateKeyError(DatabaseError):
    """Raised on unique constraint violations."""
    pass


class SchemaMismatchError(PipelineFatalError):
    """Raised when the ORM schema does not match the database schema."""
    pass


class ConfigurationError(PipelineFatalError):
    """Raised for invalid or missing configuration settings."""
    pass


class ExtractionError(JobPulseError):
    """Raised when the data extraction stage fails."""
    pass


class ExtractionFailure(ExtractionError):
    """Legacy ExtractionFailure (alias)."""
    pass


class TransformationError(JobPulseError):
    """Raised when the data transformation stage fails."""
    pass


class TransformationFailure(TransformationError):
    """Legacy TransformationFailure (alias)."""
    pass


class ValidationError(JobPulseError):
    """Raised when data validation fails."""
    pass


class ValidationFailure(ValidationError):
    """Legacy ValidationFailure (alias)."""
    pass
