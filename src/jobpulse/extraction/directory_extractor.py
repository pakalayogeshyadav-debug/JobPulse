"""jobpulse.extraction.directory_extractor — Multi-file CSV directory extractor.

Extracts raw job data by reading ALL CSV files from a directory,
combining them into a single unified DataFrame.

Use Cases:
    - A daily pipeline that drops one CSV per day into data/raw/
    - Processing a batch of exported CSV files from multiple sources
    - Ingesting a Kaggle dataset that is split across multiple files

Design Decisions:
    Source Column (_source_file):
        A '_source_file' column is added to each chunk so every row can be
        traced back to the file it came from. This supports debugging,
        de-duplication, and lineage tracking.

    Schema Alignment:
        Files may have slightly different columns (some with extra metadata
        columns, some with missing optional columns). The extractor has a
        schema_mode parameter:
            - 'strict':  All files must have identical columns. Raises on mismatch.
            - 'union':   Union all columns; missing columns become NaN.
            - 'intersect': Only keep columns present in ALL files.

    Ordering:
        Files are sorted alphabetically by name before reading, ensuring
        deterministic output regardless of filesystem ordering.

Class Hierarchy:
    BaseExtractor  (abstract)
        └── DirectoryExtractor  (this file)

Usage:
    >>> from pathlib import Path
    >>> from jobpulse.extraction.directory_extractor import DirectoryExtractor
    >>>
    >>> extractor = DirectoryExtractor(
    ...     directory=Path("data/raw/"),
    ...     glob_pattern="*.csv",
    ...     schema_mode="union",
    ... )
    >>> df, metadata = extractor.run()
    >>> print(df["_source_file"].unique())
    ['jobs_2024_01.csv', 'jobs_2024_02.csv', 'jobs_2024_03.csv']
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import pandas as pd

from jobpulse.extraction.base import (
    BaseExtractor,
    DataExtractionError,
)
from jobpulse.extraction.csv_extractor import CsvExtractor
from jobpulse.utils.file_utils import list_files

# Column added to every row to record which file it came from
_SOURCE_FILE_COLUMN = "_source_file"


class DirectoryExtractor(BaseExtractor):
    """Extracts job data from all CSV files within a directory.

    Reads each CSV file using CsvExtractor (inheriting all its robustness:
    encoding fallback, column normalisation, etc.), then concatenates all
    resulting DataFrames into one unified DataFrame.

    Attributes:
        directory:     Absolute path to the directory containing CSV files.
        glob_pattern:  Glob pattern to filter files (default: '*.csv').
        separator:     Column delimiter forwarded to each CsvExtractor.
        encoding:      File encoding forwarded to each CsvExtractor.
        schema_mode:   How to handle column mismatches between files.
                       'strict' | 'union' | 'intersect'. Default: 'union'.
        add_source_col: If True, adds '_source_file' column to each row.
        recursive:     If True, searches subdirectories recursively.
    """

    SchemaMode = Literal["strict", "union", "intersect"]

    def __init__(
        self,
        directory: Path | str,
        glob_pattern: str = "*.csv",
        separator: str = ",",
        encoding: str = "utf-8",
        schema_mode: SchemaMode = "union",
        add_source_col: bool = True,
        recursive: bool = False,
        allow_empty: bool = False,
        deduplicate: bool = True,
    ) -> None:
        """Initialise the directory extractor.

        Args:
            directory:       Path to the source directory.
            glob_pattern:    File glob pattern (e.g., '*.csv', '*.tsv',
                             'jobs_2024*.csv'). Default: '*.csv'.
            separator:       CSV column delimiter. Default: ','.
            encoding:        Primary file encoding. Default: 'utf-8'.
            schema_mode:     Column mismatch handling strategy:
                             'strict'    — All files must have identical columns.
                             'union'     — All columns across all files; NaN for missing.
                             'intersect' — Only columns common to all files.
            add_source_col:  If True, adds '_source_file' column with the
                             filename of each row's source file. Default: True.
            recursive:       If True, searches subdirectories. Default: False.
            allow_empty:     If True, 0 rows is a valid result. Default: False.
            deduplicate:     If True, drops duplicate rows across all files. Default: True.
        """
        self.directory: Path = Path(directory).resolve()
        self.glob_pattern: str = glob_pattern
        self.separator: str = separator
        self.encoding: str = encoding
        self.schema_mode: DirectoryExtractor.SchemaMode = schema_mode
        self.add_source_col: bool = add_source_col
        self.recursive: bool = recursive
        self.deduplicate: bool = deduplicate
        self._discovered_files: list[Path] = []

        super().__init__(
            source_name=f"directory:{self.directory.name}",
            allow_empty=allow_empty,
        )

    def validate_source(self) -> bool:
        """Validate the directory exists and contains at least one matching file.

        Checks:
            1. The directory path exists.
            2. The path is a directory (not a file).
            3. At least one file matches the glob pattern.

        Returns:
            bool: True if the directory is valid and has matching files.
        """
        if not self.directory.exists():
            self._logger.warning(
                "Validation failed — directory does not exist: %s", self.directory
            )
            return False

        if not self.directory.is_dir():
            self._logger.warning(
                "Validation failed — path is not a directory: %s", self.directory
            )
            return False

        try:
            files = list_files(
                self.directory,
                pattern=self.glob_pattern,
                recursive=self.recursive,
            )
        except Exception as exc:
            self._logger.warning(
                "Validation failed — error scanning directory '%s': %s",
                self.directory,
                exc,
            )
            return False

        if not files:
            self._logger.warning(
                "Validation failed — no files matching '%s' found in: %s",
                self.glob_pattern,
                self.directory,
            )
            return False

        self._discovered_files = files
        self._logger.debug(
            "Validation passed: found %d file(s) in '%s'",
            len(files),
            self.directory,
        )
        return True

    def extract(self) -> pd.DataFrame:
        """Read all matching CSV files and concatenate into one DataFrame.

        Each file is read via CsvExtractor. A '_source_file' column
        (containing the filename) is prepended when add_source_col=True.

        Returns:
            pd.DataFrame: Combined data from all files.

        Raises:
            DataExtractionError: If any individual file read fails,
                                 or if schema_mode='strict' detects a mismatch.

        Example:
            >>> df = extractor.extract()
            >>> df["_source_file"].value_counts()
            jobs_jan.csv    1200
            jobs_feb.csv    1450
            dtype: int64
        """
        # Use files cached by validate_source(), or discover them now
        if not self._discovered_files:
            self._discovered_files = list_files(
                self.directory,
                pattern=self.glob_pattern,
                recursive=self.recursive,
            )

        self._logger.info(
            "Extracting %d file(s) from directory: %s",
            len(self._discovered_files),
            self.directory,
        )

        frames: list[pd.DataFrame] = []

        for idx, file_path in enumerate(self._discovered_files, start=1):
            self._logger.info(
                "Reading file %d/%d: %s",
                idx,
                len(self._discovered_files),
                file_path.name,
            )
            frame = self._extract_single_file(file_path)

            if self.add_source_col:
                # Prepend source column so it's always the first column
                frame.insert(0, _SOURCE_FILE_COLUMN, file_path.name)

            frames.append(frame)

        if not frames:
            raise DataExtractionError(
                source_name=self.source_name,
                message="No data could be extracted from any file in the directory.",
            )

        return self._combine_frames(frames)

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _extract_single_file(self, file_path: Path) -> pd.DataFrame:
        """Extract a single CSV file using CsvExtractor.

        Args:
            file_path: Path to the CSV file to read.

        Returns:
            pd.DataFrame: Raw data from the file.

        Raises:
            DataExtractionError: If the file cannot be read.
        """
        single_extractor = CsvExtractor(
            file_path=file_path,
            separator=self.separator,
            encoding=self.encoding,
            allow_empty=True,  # Empty files get logged, not raised
            source_label=file_path.stem,
        )
        try:
            df, _ = single_extractor.run()
            return df
        except DataExtractionError as exc:
            # Re-raise with directory-level context
            raise DataExtractionError(
                source_name=self.source_name,
                message=(
                    f"Failed to extract file '{file_path.name}' "
                    f"from directory '{self.directory.name}': {exc.message}"
                ),
                cause=exc,
            ) from exc

    def _combine_frames(self, frames: list[pd.DataFrame]) -> pd.DataFrame:
        """Concatenate a list of DataFrames according to self.schema_mode.

        Args:
            frames: List of DataFrames to combine.

        Returns:
            pd.DataFrame: Combined DataFrame.

        Raises:
            DataExtractionError: If schema_mode='strict' and columns mismatch.
        """
        if self.schema_mode == "strict":
            combined = self._strict_concat(frames)
        elif self.schema_mode == "intersect":
            combined = self._intersect_concat(frames)
        else:
            # "union" — default: outer join on columns (fill missing with NaN)
            combined = self._union_concat(frames)

        if self.deduplicate and not combined.empty:
            subset_cols = [c for c in combined.columns if c != _SOURCE_FILE_COLUMN]
            before = len(combined)
            combined = combined.drop_duplicates(subset=subset_cols, ignore_index=True)
            dropped = before - len(combined)
            if dropped > 0:
                self._logger.info(
                    "Dropped %d duplicate records across all extracted files.", dropped
                )

        return combined

    def _strict_concat(self, frames: list[pd.DataFrame]) -> pd.DataFrame:
        """Concatenate frames, raising if column sets differ."""
        reference_cols = set(frames[0].columns)
        for i, frame in enumerate(frames[1:], start=2):
            if set(frame.columns) != reference_cols:
                extra = set(frame.columns) - reference_cols
                missing = reference_cols - set(frame.columns)
                raise DataExtractionError(
                    source_name=self.source_name,
                    message=(
                        f"schema_mode='strict' column mismatch at file {i}. "
                        f"Extra columns: {extra}. Missing columns: {missing}. "
                        "Use schema_mode='union' to allow column differences."
                    ),
                )
        return pd.concat(frames, ignore_index=True)

    def _union_concat(self, frames: list[pd.DataFrame]) -> pd.DataFrame:
        """Concatenate frames, filling missing columns with NaN (outer join)."""
        combined = pd.concat(frames, ignore_index=True, sort=False)
        self._logger.debug(
            "Union concat: %d rows × %d columns", len(combined), len(combined.columns)
        )
        return combined

    def _intersect_concat(self, frames: list[pd.DataFrame]) -> pd.DataFrame:
        """Concatenate frames, keeping only columns present in ALL files."""
        common_cols = set(frames[0].columns)
        for frame in frames[1:]:
            common_cols &= set(frame.columns)

        self._logger.debug(
            "Intersect concat: keeping %d common column(s)", len(common_cols)
        )
        trimmed = [frame[sorted(common_cols)] for frame in frames]
        return pd.concat(trimmed, ignore_index=True)

    def _build_extra_metadata(self) -> dict[str, Any]:
        """Include directory and file count in extraction metadata."""
        return {
            "directory": str(self.directory),
            "glob_pattern": self.glob_pattern,
            "files_processed": len(self._discovered_files),
            "schema_mode": self.schema_mode,
            "file_names": [f.name for f in self._discovered_files],
        }

    def __repr__(self) -> str:
        return (
            f"DirectoryExtractor("
            f"directory={self.directory.name!r}, "
            f"pattern={self.glob_pattern!r}, "
            f"mode={self.schema_mode!r})"
        )
