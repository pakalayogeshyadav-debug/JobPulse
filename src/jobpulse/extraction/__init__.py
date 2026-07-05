"""jobpulse.extraction — Data extraction layer.

This sub-package provides all extractors for the JobPulse ETL pipeline.
Every extractor inherits from BaseExtractor and implements the same
two-method contract, making them interchangeable to the orchestrator.

Public API:
    BaseExtractor        — Abstract base; all extractors inherit from this.
    CsvExtractor         — Reads a single local CSV file.
    DirectoryExtractor   — Reads all CSV files from a directory.
    ApiExtractor         — Abstract base for REST API extractors.

Custom Exceptions:
    DataExtractionError       — Raised on any extraction failure.
    ExtractionValidationError — Raised when source validation fails.

Value Objects:
    ExtractionMetadata  — Immutable result metadata from a run() call.

Usage:
    # Single CSV file
    >>> from pathlib import Path
    >>> from jobpulse.extraction import CsvExtractor
    >>> df, meta = CsvExtractor(Path("data/raw/jobs.csv")).run()

    # All CSVs in a directory
    >>> from jobpulse.extraction import DirectoryExtractor
    >>> df, meta = DirectoryExtractor(Path("data/raw/")).run()

    # Custom API extractor (subclass ApiExtractor)
    >>> from jobpulse.extraction import ApiExtractor
    >>> class MyApi(ApiExtractor):
    ...     def _build_request_params(self, page): ...
    ...     def _parse_response(self, data): ...
"""

from jobpulse.extraction.api_extractor import ApiExtractor
from jobpulse.extraction.base import (
    BaseExtractor,
    DataExtractionError,
    ExtractionMetadata,
    ExtractionValidationError,
)
from jobpulse.extraction.csv_extractor import CsvExtractor
from jobpulse.extraction.directory_extractor import DirectoryExtractor

__all__ = [
    # Base
    "BaseExtractor",
    "DataExtractionError",
    "ExtractionValidationError",
    "ExtractionMetadata",
    # Concrete extractors
    "CsvExtractor",
    "DirectoryExtractor",
    "ApiExtractor",
]
