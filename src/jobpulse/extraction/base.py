"""jobpulse.extraction.base — Abstract base class for all extractors.

Defines the contract that every extractor must fulfil.
The pipeline orchestrator works against this interface — it does not
care whether data comes from a CSV, a REST API, or S3.

Design Patterns Used:
    Strategy Pattern:
        The orchestrator selects an extractor at runtime based on
        configuration. All extractors are interchangeable because they
        share the same BaseExtractor interface.

    Template Method Pattern:
        BaseExtractor.run() defines the algorithm skeleton:
            1. Log start
            2. validate_source()   ← subclass implements
            3. extract()           ← subclass implements
            4. _post_extract_checks()  ← shared guard (empty-frame check)
            5. Log completion metrics
        Subclasses override only the steps that differ, not the skeleton.

Abstract Methods (subclasses MUST implement):
    extract()         — Fetch raw data and return as a DataFrame.
    validate_source() — Check whether the source is accessible.

Concrete Methods (inherited as-is):
    run()              — Orchestrates validate → extract → check.
    get_metadata()     — Returns a dict of extraction metadata.

Custom Exception:
    DataExtractionError — Raised on any extraction failure.
    ExtractionValidationError — Raised when source cannot be reached.

Usage:
    >>> class MyExtractor(BaseExtractor):
    ...     def validate_source(self) -> bool:
    ...         return True
    ...     def extract(self) -> pd.DataFrame:
    ...         return pd.DataFrame({"col": [1, 2, 3]})
    ...
    >>> result = MyExtractor(source_name="my_source").run()
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from jobpulse.logging.logger import get_logger

# Module-level logger for shared messages (not tied to a specific source)
logger = get_logger(__name__)


# =============================================================================
# Custom Exceptions
# =============================================================================


class DataExtractionError(Exception):
    """Raised when data extraction fails for any recoverable or unrecoverable reason.

    This is the single exception type raised by the extraction layer.
    Callers catch this to handle failures gracefully (retry, alert, skip).

    Attributes:
        source_name: Identifier of the failing data source.
        message:     Human-readable description of the failure.
        cause:       The original exception that triggered this error (if any).

    Examples:
        - Local file not found or not readable
        - HTTP 4xx / 5xx response from an API
        - Network timeout or DNS resolution failure
        - Malformed CSV structure (wrong number of columns)
        - Empty file when rows were expected

    Example:
        >>> raise DataExtractionError("csv", "File not found: /data/raw/jobs.csv")
    """

    def __init__(
        self,
        source_name: str,
        message: str,
        cause: BaseException | None = None,
    ) -> None:
        """Initialise the extraction error.

        Args:
            source_name: Short identifier of the data source (e.g., 'csv', 'adzuna').
            message:     Human-readable description of what went wrong.
            cause:       The original exception, if this is being raised from
                         an ``except`` block. Used for exception chaining context.
        """
        self.source_name = source_name
        self.message = message
        self.cause = cause
        super().__init__(f"[{source_name}] Extraction failed: {message}")


class ExtractionValidationError(DataExtractionError):
    """Raised specifically when source validation fails (before extraction begins).

    Signals that the source itself is unreachable or misconfigured, as opposed
    to a failure that occurs during the actual data read.

    Example:
        - File path does not exist
        - API key is missing
        - S3 bucket is not accessible
    """


# =============================================================================
# Extraction Metadata Value Object
# =============================================================================


@dataclass(frozen=True)
class ExtractionMetadata:
    """Immutable record of metrics from a single extraction run.

    Produced by BaseExtractor.run() after every successful extraction.
    Useful for pipeline orchestrators, logging dashboards, and audit tables.

    Attributes:
        source_name:    Identifier of the data source.
        rows_extracted: Number of rows in the returned DataFrame.
        columns:        List of column names in the returned DataFrame.
        started_at:     UTC timestamp when extraction began.
        completed_at:   UTC timestamp when extraction completed.
        duration_ms:    Wall-clock duration of extraction in milliseconds.
        extra:          Optional dict of source-specific additional metadata.
    """

    source_name: str
    rows_extracted: int
    columns: list[str]
    started_at: datetime
    completed_at: datetime
    duration_ms: float
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        """Return duration in seconds, rounded to 3 decimal places."""
        return round(self.duration_ms / 1000.0, 3)

    def to_log_string(self) -> str:
        """Format metadata as a single-line log message string.

        Returns:
            str: Human-readable summary suitable for log output.
        """
        return (
            f"source={self.source_name!r} "
            f"rows={self.rows_extracted} "
            f"cols={len(self.columns)} "
            f"duration={self.duration_seconds:.3f}s"
        )


# =============================================================================
# Abstract Base Extractor
# =============================================================================


class BaseExtractor(ABC):
    """Abstract base class defining the extraction contract for all extractors.

    Every concrete extractor (CsvExtractor, ApiExtractor, DirectoryExtractor, ...)
    inherits from this class and implements two abstract methods:
        - validate_source() → bool
        - extract()         → pd.DataFrame

    The run() method is the public entry point. It orchestrates the full
    extraction lifecycle using the Template Method Pattern:
        1. Record start time
        2. Call validate_source() — raises ExtractionValidationError on failure
        3. Call extract()         — raises DataExtractionError on failure
        4. Run post-extraction guards (empty-frame check)
        5. Build and return ExtractionMetadata

    Subclasses should NOT override run(). They override only extract()
    and validate_source() to implement source-specific logic.

    Attributes:
        source_name:      Short identifier string (e.g., 'csv', 'adzuna').
        allow_empty:      If False (default), run() raises if extract() returns
                          an empty DataFrame. Set to True for sources that can
                          legitimately return 0 rows.
        _logger:          Named child logger for this extractor instance.
        _last_metadata:   Populated after each successful run() call.
    """

    def __init__(
        self,
        source_name: str,
        allow_empty: bool = False,
    ) -> None:
        """Initialise the base extractor.

        Args:
            source_name:  Short, machine-readable identifier for this source.
                          Used in log messages, error messages, and metadata.
                          Examples: 'csv', 'adzuna_api', 'usajobs_api'.
            allow_empty:  Whether to allow an empty (0-row) DataFrame as a
                          valid extraction result. Defaults to False.
        """
        self.source_name: str = source_name
        self.allow_empty: bool = allow_empty
        self._logger = get_logger(f"jobpulse.extraction.{source_name}")
        self._last_metadata: ExtractionMetadata | None = None

    # ─────────────────────────────────────────────────────────────────────────
    # Abstract Interface — subclasses MUST implement these two methods
    # ─────────────────────────────────────────────────────────────────────────

    @abstractmethod
    def validate_source(self) -> bool:
        """Validate that the data source is accessible before extraction begins.

        Called automatically by run() before extract(). Implementors should
        perform the lightest possible check that confirms the source is usable:
            - File-based sources: check file exists and is readable
            - API-based sources:  check credentials are set, optionally ping
            - Directory sources:  check directory exists and contains files

        Contract:
            - MUST return True if the source is ready to be extracted from.
            - MUST return False (not raise) if the source is unavailable.
            - Must NOT raise exceptions — all errors become a ``return False``.

        Returns:
            bool: True if the source is accessible and ready, False otherwise.
        """
        ...

    @abstractmethod
    def extract(self) -> pd.DataFrame:
        """Extract raw data from the source and return as a Pandas DataFrame.

        Called automatically by run() after validate_source() returns True.

        Contract:
            - MUST return a pd.DataFrame (possibly empty if allow_empty=True).
            - MUST raise DataExtractionError on any failure.
            - Must NOT perform data transformation — return data as received.
            - Must NOT call validate_source() internally.

        Returns:
            pd.DataFrame: Raw data exactly as received from the source.
                          All columns should be str dtype for safety
                          (type casting happens in the transformation layer).

        Raises:
            DataExtractionError: If extraction fails for any reason.
        """
        ...

    # ─────────────────────────────────────────────────────────────────────────
    # Template Method — the public entry point
    # ─────────────────────────────────────────────────────────────────────────

    def run(self) -> tuple[pd.DataFrame, ExtractionMetadata]:
        """Execute the full extraction lifecycle (Template Method).

        Orchestrates: validate → extract → guard checks → metadata.
        This is the method the pipeline orchestrator calls.

        Returns:
            tuple[pd.DataFrame, ExtractionMetadata]:
                - The raw DataFrame produced by extract().
                - Metadata about the extraction (timing, row count, columns).

        Raises:
            ExtractionValidationError: If validate_source() returns False.
            DataExtractionError:       If extract() raises or returns empty
                                       data when allow_empty=False.

        Example:
            >>> extractor = CsvExtractor(file_path=Path("data/raw/jobs.csv"))
            >>> df, meta = extractor.run()
            >>> print(f"Extracted {meta.rows_extracted} rows in {meta.duration_seconds}s")
        """
        self._logger.info("Starting extraction | source='%s'", self.source_name)

        # ── Step 1: Validate source ───────────────────────────────────────────
        started_at = datetime.now(tz=UTC)
        t0 = time.perf_counter()

        self._run_validation()  # raises ExtractionValidationError on False

        # ── Step 2: Extract data ──────────────────────────────────────────────
        df = self._run_extraction()  # raises DataExtractionError on failure

        # ── Step 3: Post-extraction guards ────────────────────────────────────
        self._post_extract_checks(df)

        # ── Step 4: Build metadata ────────────────────────────────────────────
        completed_at = datetime.now(tz=UTC)
        duration_ms = (time.perf_counter() - t0) * 1000.0

        metadata = ExtractionMetadata(
            source_name=self.source_name,
            rows_extracted=len(df),
            columns=list(df.columns),
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            extra=self._build_extra_metadata(),
        )
        self._last_metadata = metadata

        self._logger.info("Extraction complete | %s", metadata.to_log_string())
        return df, metadata

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers — orchestration internals
    # ─────────────────────────────────────────────────────────────────────────

    def _run_validation(self) -> bool:
        """Execute validate_source() and raise ExtractionValidationError on failure.

        Returns:
            bool: Always True (raises instead of returning False).

        Raises:
            ExtractionValidationError: If validate_source() returns False.
        """
        self._logger.debug("Validating source: '%s'", self.source_name)
        try:
            is_valid = self.validate_source()
        except Exception as exc:
            self._logger.error(
                "validate_source() raised unexpectedly for '%s': %s",
                self.source_name,
                exc,
            )
            raise ExtractionValidationError(
                source_name=self.source_name,
                message=f"Validation raised an unexpected exception: {exc}",
                cause=exc,
            ) from exc

        if not is_valid:
            self._logger.error(
                "Source validation FAILED for '%s'. "
                "Check that the source exists and is accessible.",
                self.source_name,
            )
            raise ExtractionValidationError(
                source_name=self.source_name,
                message="Source is unreachable or invalid. "
                "Check file path, credentials, or network connectivity.",
            )

        self._logger.debug("Source validation PASSED for '%s'.", self.source_name)
        return True

    def _run_extraction(self) -> pd.DataFrame:
        """Execute extract() and wrap any non-DataExtractionError exceptions.

        Returns:
            pd.DataFrame: Raw data from the source.

        Raises:
            DataExtractionError: On any failure inside extract().
        """
        try:
            df = self.extract()
        except DataExtractionError:
            # Already the correct type — re-raise without wrapping
            raise
        except Exception as exc:
            # Wrap unexpected errors so the orchestrator only has one type to handle
            self._logger.exception(
                "Unexpected error during extract() for source '%s': %s",
                self.source_name,
                exc,
            )
            raise DataExtractionError(
                source_name=self.source_name,
                message=f"Unexpected error: {type(exc).__name__}: {exc}",
                cause=exc,
            ) from exc
        return df

    def _post_extract_checks(self, df: pd.DataFrame) -> None:
        """Run sanity checks on the extracted DataFrame.

        Currently checks:
            - DataFrame is not empty (unless self.allow_empty is True)

        Additional checks can be added here without changing subclasses.

        Args:
            df: The DataFrame returned by extract().

        Raises:
            DataExtractionError: If the DataFrame fails any guard check.
        """
        if df.empty and not self.allow_empty:
            raise DataExtractionError(
                source_name=self.source_name,
                message=(
                    "extract() returned an empty DataFrame (0 rows). "
                    "The source may be empty or the query returned no results. "
                    "If this is expected, set allow_empty=True."
                ),
            )

        if not isinstance(df, pd.DataFrame):
            raise DataExtractionError(
                source_name=self.source_name,
                message=(
                    f"extract() must return a pd.DataFrame, "
                    f"got {type(df).__name__} instead."
                ),
            )

    def _build_extra_metadata(self) -> dict[str, Any]:
        """Build a source-specific extras dictionary for ExtractionMetadata.

        Subclasses may override this to add source-specific info
        (e.g., file path, API endpoint, page count) to the metadata record.

        Returns:
            dict[str, Any]: Extra key-value pairs. Default is empty dict.
        """
        return {}

    # ─────────────────────────────────────────────────────────────────────────
    # Public utility methods
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def last_metadata(self) -> ExtractionMetadata | None:
        """Return the metadata from the most recent run() call.

        Returns:
            ExtractionMetadata | None: Metadata object, or None if run()
                                       has not been called yet.
        """
        return self._last_metadata

    def __repr__(self) -> str:
        """Return a developer-friendly string representation."""
        return (
            f"{self.__class__.__name__}("
            f"source_name={self.source_name!r}, "
            f"allow_empty={self.allow_empty!r})"
        )
