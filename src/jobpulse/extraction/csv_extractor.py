"""jobpulse.extraction.csv_extractor — Production CSV file extractor.

Extracts raw job data from a single CSV file on the local filesystem.
Used for ingesting:
    - Kaggle job posting datasets (e.g., linkedin-job-postings)
    - Flat-file exports from third-party job boards
    - Sample files for development and testing

Design Decisions:
    dtype=str:
        All columns are read as strings. This is intentional.
        Type casting (int, float, datetime) happens in the Transformation
        layer. Reading everything as str prevents Pandas from silently
        mis-inferring types (e.g., reading "2024" as int when it's a year).

    low_memory=False:
        Forces Pandas to read the entire file before inferring column types,
        avoiding the DtypeWarning that triggers on large mixed-type columns.

    Encoding detection:
        The extractor first tries the supplied encoding (default: 'utf-8').
        If that fails with a UnicodeDecodeError, it falls back to 'latin-1'
        (also known as ISO-8859-1), which can decode any byte sequence.

    Column normalisation:
        Column names are stripped of leading/trailing whitespace and
        lowercased. This is the only normalisation step performed here —
        it is not considered transformation because it is structural
        (making the DataFrame usable), not semantic (changing data values).

Class Hierarchy:
    BaseExtractor   (abstract)
        └── CsvExtractor  (this file)

Usage:
    >>> from pathlib import Path
    >>> from jobpulse.extraction.csv_extractor import CsvExtractor
    >>>
    >>> extractor = CsvExtractor(file_path=Path("data/raw/jobs_2024.csv"))
    >>> df, metadata = extractor.run()
    >>> print(df.shape)
    (50000, 14)
    >>> print(metadata.duration_seconds)
    0.843
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import tenacity

from jobpulse.extraction.base import (
    BaseExtractor,
    DataExtractionError,
)


class CsvExtractor(BaseExtractor):
    """Extracts raw job data from a single local CSV file.

    Reads the file into a Pandas DataFrame, keeping all values as strings
    to preserve data fidelity. Delegates type conversion to the
    transformation layer.

    Supports:
        - Custom column delimiters (tab-separated, pipe-separated, etc.)
        - Custom file encodings (UTF-8, Latin-1, UTF-16, etc.)
        - Automatic encoding fallback (UTF-8 → Latin-1)
        - Skipping header rows
        - Selecting a subset of columns to load
        - Chunked reading for memory-efficient loading of large files

    Attributes:
        file_path:       Resolved absolute path to the CSV file.
        separator:       Column delimiter character (default: ',').
        encoding:        Primary file encoding to attempt (default: 'utf-8').
        skip_rows:       Number of rows to skip at the top of the file.
        use_columns:     If set, only these columns are loaded from the file.
        chunk_size:      If set, reads the file in chunks of this many rows.
                         When set, extract() returns the first chunk only
                         (the pipeline should call extract_chunks() instead).
        source_label:    Human-readable label used in logs and metadata.
                         Defaults to the file's name (stem).
    """

    # Fallback encoding when primary encoding fails to decode the file
    _ENCODING_FALLBACK: str = "latin-1"

    def __init__(
        self,
        file_path: Path | str,
        separator: str = ",",
        encoding: str = "utf-8",
        skip_rows: int = 0,
        use_columns: list[str] | None = None,
        chunk_size: int | None = None,
        allow_empty: bool = False,
        source_label: str | None = None,
    ) -> None:
        """Initialise the CSV extractor.

        Args:
            file_path:    Path to the CSV file. Accepts str or Path.
                          Resolved to an absolute path internally.
            separator:    Column delimiter. Defaults to ',' (standard CSV).
                          Use '\\t' for TSV, '|' for pipe-separated.
            encoding:     File encoding. Defaults to 'utf-8'.
                          Falls back to 'latin-1' if UTF-8 decoding fails.
            skip_rows:    Number of rows to skip at the start of the file
                          (e.g., to skip metadata header rows). Default: 0.
            use_columns:  Optional list of column names to load.
                          If None, all columns are loaded. If set, only
                          the named columns are included in the DataFrame.
            chunk_size:   Number of rows per chunk for large-file processing.
                          When set, extract() reads and returns the first
                          chunk. Use extract_chunks() for full iteration.
            allow_empty:  If True, an empty DataFrame is a valid result.
                          Defaults to False (empty file raises error).
            source_label: Optional label for logging. Defaults to file name.

        Example:
            >>> extractor = CsvExtractor(
            ...     file_path=Path("data/raw/linkedin_jobs.csv"),
            ...     separator=",",
            ...     encoding="utf-8",
            ...     use_columns=["title", "company", "location", "salary"],
            ... )
        """
        self.file_path: Path = Path(file_path).resolve()
        self.separator: str = separator
        self.encoding: str = encoding
        self.skip_rows: int = skip_rows
        self.use_columns: list[str] | None = use_columns
        self.chunk_size: int | None = chunk_size

        # Use file stem as source label if not provided (e.g., "linkedin_jobs")
        label = source_label or self.file_path.stem
        super().__init__(source_name=label, allow_empty=allow_empty)

    # ─────────────────────────────────────────────────────────────────────────
    # Abstract method implementations (required by BaseExtractor)
    # ─────────────────────────────────────────────────────────────────────────

    def validate_source(self) -> bool:
        """Validate that the CSV file exists, is a regular file, and is readable.

        Checks performed:
            1. Path exists on the filesystem.
            2. Path points to a regular file (not a directory or symlink loop).
            3. File has read permission.
            4. File is not completely empty (0 bytes).

        Returns:
            bool: True if all checks pass. False if any check fails
                  (logs a warning describing which check failed).

        Note:
            This method never raises — all failures are caught and logged,
            then signalled via ``return False``.
        """
        # Check 1: File exists
        if not self.file_path.exists():
            self._logger.warning(
                "Validation failed — file does not exist: %s", self.file_path
            )
            return False

        # Check 2: Is a regular file
        if not self.file_path.is_file():
            self._logger.warning(
                "Validation failed — path is not a regular file: %s",
                self.file_path,
            )
            return False

        # Check 3: File is readable (attempt open)
        try:
            self.file_path.open("r").close()
        except PermissionError:
            self._logger.warning(
                "Validation failed — no read permission on file: %s",
                self.file_path,
            )
            return False

        # Check 4: File is not completely empty
        if self.file_path.stat().st_size == 0:
            self._logger.warning(
                "Validation failed — file is empty (0 bytes): %s",
                self.file_path,
            )
            return False

        self._logger.debug(
            "Validation passed for CSV file: %s (%.1f KB)",
            self.file_path,
            self.file_path.stat().st_size / 1024,
        )
        return True

    def extract(self) -> pd.DataFrame:
        """Read the CSV file and return its contents as a raw DataFrame.

        All values are read as strings (dtype=str). Column names are
        stripped of whitespace and lowercased for consistency.

        If the primary encoding fails, automatically retries with
        the Latin-1 fallback encoding.

        Returns:
            pd.DataFrame: Raw data from the CSV file.
                          Shape: (n_rows, n_columns).
                          All column dtypes: object (str).

        Raises:
            DataExtractionError: If the file cannot be read for any reason
                                 (encoding error, parse error, IO error).

        Example:
            >>> df = extractor.extract()
            >>> df.dtypes.unique()
            array([dtype('O')], dtype=object)  # all object (str)
        """
        self._logger.info(
            "Reading CSV file: %s | encoding=%s | sep=%r",
            self.file_path,
            self.encoding,
            self.separator,
        )

        # First attempt: use the configured primary encoding
        df = self._read_csv(encoding=self.encoding)

        # If primary encoding produced no result and we haven't tried fallback yet
        if df is None:
            self._logger.warning(
                "Primary encoding '%s' failed for '%s'. "
                "Retrying with fallback encoding '%s'.",
                self.encoding,
                self.file_path,
                self._ENCODING_FALLBACK,
            )
            df = self._read_csv(encoding=self._ENCODING_FALLBACK)

        # If both attempts failed, df is still None — raise
        if df is None:
            raise DataExtractionError(
                source_name=self.source_name,
                message=(
                    f"Failed to read '{self.file_path}' with encodings "
                    f"['{self.encoding}', '{self._ENCODING_FALLBACK}']. "
                    "Check that the file is a valid CSV and specify the "
                    "correct encoding via the 'encoding' parameter."
                ),
            )

        # Normalise column names: strip whitespace, lowercase
        df = self._normalise_column_names(df)

        # Validate that requested columns exist (if use_columns was specified)
        if self.use_columns:
            self._validate_requested_columns(df)

        self._logger.debug(
            "CSV read complete: %d rows × %d columns | file=%s",
            len(df),
            len(df.columns),
            self.file_path.name,
        )
        return df

    # ─────────────────────────────────────────────────────────────────────────
    # Public methods for advanced usage
    # ─────────────────────────────────────────────────────────────────────────

    def extract_chunks(self) -> pd.DataFrame:
        """Iterate over the CSV file in chunks, yielding one DataFrame per chunk.

        Designed for memory-efficient processing of very large files
        (hundreds of MB or multi-GB CSVs that don't fit in RAM).

        chunk_size must be set in the constructor for this method to work.

        Yields:
            pd.DataFrame: A chunk of ``chunk_size`` rows (or fewer for the
                          last chunk). All values are strings.

        Raises:
            DataExtractionError: If chunk_size is not set, or if reading fails.
            ExtractionValidationError: If the file fails validation.

        Example:
            >>> extractor = CsvExtractor(
            ...     file_path=Path("data/raw/large_jobs.csv"),
            ...     chunk_size=5000,
            ... )
            >>> for chunk_df in extractor.extract_chunks():
            ...     process(chunk_df)  # transform and load in batches
        """
        if self.chunk_size is None:
            raise DataExtractionError(
                source_name=self.source_name,
                message=(
                    "extract_chunks() requires chunk_size to be set. "
                    "Pass chunk_size=<int> to the CsvExtractor constructor."
                ),
            )

        self._logger.info(
            "Starting chunked extraction | file=%s | chunk_size=%d",
            self.file_path.name,
            self.chunk_size,
        )

        # Validate before iterating (fail fast)
        self._run_validation()

        chunk_index = 0
        try:
            reader = pd.read_csv(
                self.file_path,
                sep=self.separator,
                encoding=self.encoding,
                dtype=str,
                keep_default_na=False,
                skiprows=self.skip_rows if self.skip_rows > 0 else None,
                usecols=self.use_columns,
                low_memory=False,
                chunksize=self.chunk_size,
            )
            for chunk_df in reader:
                chunk_df = self._normalise_column_names(chunk_df)
                chunk_index += 1
                self._logger.debug(
                    "Yielding chunk %d: %d rows", chunk_index, len(chunk_df)
                )
                yield chunk_df

        except Exception as exc:
            raise DataExtractionError(
                source_name=self.source_name,
                message=f"Failed reading chunk {chunk_index + 1}: {exc}",
                cause=exc,
            ) from exc

        self._logger.info(
            "Chunked extraction complete | %d chunks | file=%s",
            chunk_index,
            self.file_path.name,
        )

    def get_file_info(self) -> dict[str, Any]:
        """Return a dictionary of file-level metadata without reading data.

        Useful for logging, monitoring, and pre-extraction size checks.

        Returns:
            dict[str, Any]: File metadata including path, size, and timestamps.

        Raises:
            FileNotFoundError: If the file does not exist.

        Example:
            >>> info = extractor.get_file_info()
            >>> print(info["size_mb"])
            12.4
        """
        if not self.file_path.exists():
            raise FileNotFoundError(f"File not found: {self.file_path}")

        stat = self.file_path.stat()
        return {
            "file_name": self.file_path.name,
            "file_path": str(self.file_path),
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / (1024**2), 2),
            "extension": self.file_path.suffix,
            "separator": self.separator,
            "encoding": self.encoding,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(OSError),
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _read_csv(self, encoding: str) -> pd.DataFrame | None:
        """Attempt to read the CSV file with the given encoding.

        Returns None (rather than raising) so the caller can transparently
        fall back to an alternative encoding.

        Args:
            encoding: The character encoding to use when decoding the file.

        Returns:
            pd.DataFrame | None: The loaded DataFrame, or None if reading
                                 failed due to a UnicodeDecodeError or
                                 EmptyDataError.

        Raises:
            DataExtractionError: For non-encoding errors (IO errors,
                                 CSV parse errors, etc.).
        """
        try:
            df: pd.DataFrame = pd.read_csv(
                self.file_path,
                sep=self.separator,
                encoding=encoding,
                dtype=str,  # All values as strings — type cast in transform
                keep_default_na=False,  # Don't convert 'NA', 'None' to NaN here
                na_values=["", " "],  # Only genuine blanks become NaN
                skiprows=self.skip_rows if self.skip_rows > 0 else None,
                usecols=self.use_columns,
                low_memory=False,  # Avoids DtypeWarning on mixed columns
            )
            return df

        except UnicodeDecodeError:
            # Expected on encoding mismatch — caller handles the fallback
            return None

        except pd.errors.EmptyDataError:
            # File has a header row but zero data rows
            self._logger.warning("CSV file has no data rows: %s", self.file_path)
            return pd.DataFrame()  # Return empty DataFrame, not None

        except ValueError as exc:
            if "Usecols do not match" in str(exc):
                # Pandas raises ValueError if usecols contains columns not in the CSV
                raise DataExtractionError(
                    source_name=self.source_name,
                    message=str(exc),
                    cause=exc,
                ) from exc
            raise DataExtractionError(
                source_name=self.source_name,
                message=f"Value error reading '{self.file_path}': {exc}",
                cause=exc,
            ) from exc

        except pd.errors.ParserError as exc:
            raise DataExtractionError(
                source_name=self.source_name,
                message=(
                    f"CSV parse error in '{self.file_path.name}': {exc}. "
                    "Check that the separator is correct "
                    f"(currently set to {self.separator!r})."
                ),
                cause=exc,
            ) from exc

        except OSError as exc:
            raise DataExtractionError(
                source_name=self.source_name,
                message=f"OS-level error reading '{self.file_path}': {exc}",
                cause=exc,
            ) from exc

    def _normalise_column_names(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalise DataFrame column names to lowercase with stripped whitespace.

        This is a structural operation, not a transformation. It makes column
        names consistent and predictable for downstream code, regardless of
        how the source file formatted its header row.

        Normalisation steps:
            1. Convert to string (handles multi-index or numeric columns)
            2. Strip leading/trailing whitespace
            3. Lowercase all characters
            4. Replace internal whitespace sequences with underscores
            5. Remove any remaining non-alphanumeric characters (except '_')

        Args:
            df: DataFrame with potentially messy column names.

        Returns:
            pd.DataFrame: Same data with normalised column names.

        Example:
            Input columns:  ['Job Title', ' Company Name ', 'Posted Date']
            Output columns: ['job_title', 'company_name', 'posted_date']
        """
        import re

        original_columns = list(df.columns)
        normalised = [
            re.sub(
                r"[^\w]",
                "_",  # Replace non-word chars with _
                re.sub(
                    r"\s+",
                    "_",  # Replace whitespace runs with _
                    str(col).strip().lower(),  # Strip + lowercase
                ),
            ).strip(
                "_"
            )  # Remove leading/trailing _
            for col in original_columns
        ]

        # Log if any columns were renamed
        renamed = {
            orig: norm
            for orig, norm in zip(original_columns, normalised)
            if orig != norm
        }
        if renamed:
            self._logger.debug(
                "Column names normalised (%d renamed): %s",
                len(renamed),
                renamed,
            )

        df.columns = pd.Index(normalised)
        return df

    def _validate_requested_columns(self, df: pd.DataFrame) -> None:
        """Verify that all columns in self.use_columns exist in the DataFrame.

        Called after normalisation, so comparison is against lowercased names.

        Args:
            df: The loaded (and column-normalised) DataFrame.

        Raises:
            DataExtractionError: If any requested column is absent from the file.
        """
        if self.use_columns is None:
            return

        # Normalise the requested column names the same way we normalise headers
        import re

        normalised_requested = [
            re.sub(r"[^\w]", "_", re.sub(r"\s+", "_", str(col).strip().lower())).strip(
                "_"
            )
            for col in self.use_columns
        ]

        available = set(df.columns)
        missing = [col for col in normalised_requested if col not in available]

        if missing:
            raise DataExtractionError(
                source_name=self.source_name,
                message=(
                    f"Requested columns not found in '{self.file_path.name}': "
                    f"{missing}. "
                    f"Available columns: {sorted(available)}"
                ),
            )

    def _build_extra_metadata(self) -> dict[str, Any]:
        """Extend ExtractionMetadata with CSV-specific file information.

        Overrides BaseExtractor._build_extra_metadata() to include
        file path and size in the metadata record.

        Returns:
            dict[str, Any]: CSV-specific metadata fields.
        """
        extra: dict[str, Any] = {
            "file_path": str(self.file_path),
            "file_name": self.file_path.name,
            "separator": self.separator,
            "encoding": self.encoding,
        }
        if self.file_path.exists():
            extra["size_bytes"] = self.file_path.stat().st_size
        return extra

    def __repr__(self) -> str:
        """Return a developer-friendly string representation."""
        return (
            f"CsvExtractor("
            f"file={self.file_path.name!r}, "
            f"sep={self.separator!r}, "
            f"encoding={self.encoding!r})"
        )
