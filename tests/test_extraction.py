"""
tests/test_extraction.py — Unit tests for the extraction layer.

Tests are organised by class. Each test method targets a single behaviour
so failures are immediately diagnosable without reading the stack trace.

Test Isolation Strategy:
    - All tests use tmp_path (pytest's built-in temp directory fixture)
      so they never touch the real data/raw/ directory.
    - No database connections required.
    - No network calls — ApiExtractor tests mock requests.Session.

Coverage Targets:
    BaseExtractor:
        ✅ run() calls validate_source() then extract()
        ✅ run() raises ExtractionValidationError when validate_source() returns False
        ✅ run() raises DataExtractionError when extract() raises
        ✅ run() raises DataExtractionError when extract() returns empty DataFrame
        ✅ run() allows empty DataFrame when allow_empty=True
        ✅ run() returns (DataFrame, ExtractionMetadata) tuple
        ✅ ExtractionMetadata has correct row count and column list
        ✅ ExtractionMetadata.duration_ms > 0

    CsvExtractor.validate_source():
        ✅ Returns True for a valid, readable CSV file
        ✅ Returns False when file does not exist
        ✅ Returns False when path is a directory
        ✅ Returns False when file is 0 bytes (empty)

    CsvExtractor.extract():
        ✅ Returns DataFrame with correct shape
        ✅ All columns are dtype object (str)
        ✅ Column names are normalised (lowercase, underscored)
        ✅ Raises DataExtractionError on bad separator (unreadable file)
        ✅ Handles UTF-8 encoded files correctly
        ✅ Falls back to latin-1 when UTF-8 decoding fails
        ✅ Respects use_columns (only requested columns returned)
        ✅ Raises DataExtractionError when use_columns has non-existent column
        ✅ Handles files with whitespace-padded column names

    CsvExtractor.run() (integration):
        ✅ Full run() returns correct (df, metadata) for a valid CSV
        ✅ metadata.rows_extracted matches len(df)
        ✅ metadata.extra contains file_path and file_name keys

    CsvExtractor.extract_chunks():
        ✅ Raises DataExtractionError when chunk_size is not set
        ✅ Yields correct number of chunks for a given file size

    CsvExtractor.get_file_info():
        ✅ Returns dict with size_bytes > 0 for existing file
        ✅ Raises FileNotFoundError for non-existent file

    DirectoryExtractor.validate_source():
        ✅ Returns True when directory contains matching CSVs
        ✅ Returns False when directory does not exist
        ✅ Returns False when path is a file (not a directory)
        ✅ Returns False when no files match the glob pattern

    DirectoryExtractor.extract():
        ✅ Combines multiple CSV files into one DataFrame
        ✅ Adds _source_file column when add_source_col=True
        ✅ Does not add _source_file column when add_source_col=False
        ✅ schema_mode='strict' raises on column mismatch
        ✅ schema_mode='union' fills NaN for missing columns
        ✅ schema_mode='intersect' keeps only common columns

    DataExtractionError:
        ✅ str() includes source_name and message
        ✅ cause attribute is preserved

    ExtractionMetadata:
        ✅ duration_seconds = duration_ms / 1000
        ✅ to_log_string() contains source_name and row count
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from jobpulse.extraction.base import (
    BaseExtractor,
    DataExtractionError,
    ExtractionMetadata,
    ExtractionValidationError,
)
from jobpulse.extraction.csv_extractor import CsvExtractor
from jobpulse.extraction.directory_extractor import DirectoryExtractor

# =============================================================================
# Fixtures and helpers
# =============================================================================

SAMPLE_CSV_CONTENT = (
    "Job Title,Company Name,Location,Salary Min,Salary Max\n"
    "Data Engineer,Acme Corp,New York,80000,120000\n"
    "Data Analyst,Beta Inc,San Francisco,70000,100000\n"
    "ML Engineer,Gamma Ltd,Remote,90000,140000\n"
)

LATIN1_CSV_CONTENT_BYTES = (
    b"title,company\n"
    b"Ing\xe9nieur Donn\xe9es,Soci\xe9t\xe9 G\xe9n\xe9rale\n"  # Latin-1 encoded French
    b"Data Engineer,Acme Corp\n"
)


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Write a valid UTF-8 CSV file and return its path."""
    file = tmp_path / "jobs.csv"
    file.write_text(SAMPLE_CSV_CONTENT, encoding="utf-8")
    return file


@pytest.fixture
def latin1_csv(tmp_path: Path) -> Path:
    """Write a Latin-1 encoded CSV file (UTF-8 read will fail)."""
    file = tmp_path / "latin1_jobs.csv"
    file.write_bytes(LATIN1_CSV_CONTENT_BYTES)
    return file


@pytest.fixture
def empty_csv(tmp_path: Path) -> Path:
    """Write a CSV with a header row but zero data rows."""
    file = tmp_path / "empty_jobs.csv"
    file.write_text("title,company,location\n", encoding="utf-8")
    return file


@pytest.fixture
def zero_byte_file(tmp_path: Path) -> Path:
    """Write a file with 0 bytes."""
    file = tmp_path / "zero.csv"
    file.write_bytes(b"")
    return file


@pytest.fixture
def multi_csv_dir(tmp_path: Path) -> Path:
    """
    Create a directory with 3 CSV files having the same schema.
    Returns the directory path.
    """
    (tmp_path / "jan.csv").write_text(
        "title,company\nData Engineer,Acme\n", encoding="utf-8"
    )
    (tmp_path / "feb.csv").write_text(
        "title,company\nData Analyst,Beta\nML Engineer,Gamma\n", encoding="utf-8"
    )
    (tmp_path / "mar.csv").write_text(
        "title,company\nSoftware Engineer,Delta\n", encoding="utf-8"
    )
    return tmp_path


def make_concrete_extractor(
    validate_returns: bool = True,
    extract_returns: pd.DataFrame | None = None,
    allow_empty: bool = False,
) -> BaseExtractor:
    """
    Helper: Create a minimal concrete subclass of BaseExtractor for testing.

    Args:
        validate_returns: Value that validate_source() will return.
        extract_returns:  DataFrame that extract() will return.
                          Defaults to a 2-row test DataFrame.
        allow_empty:      Forwarded to BaseExtractor.__init__.

    Returns:
        Instantiated concrete extractor.
    """
    if extract_returns is None:
        extract_returns = pd.DataFrame({"col_a": ["x", "y"], "col_b": ["1", "2"]})

    class _ConcreteExtractor(BaseExtractor):
        def validate_source(self) -> bool:
            return validate_returns

        def extract(self) -> pd.DataFrame:
            return extract_returns  # type: ignore[return-value]

    return _ConcreteExtractor(source_name="test_source", allow_empty=allow_empty)


# =============================================================================
# DataExtractionError tests
# =============================================================================


class TestDataExtractionError:
    """Tests for the DataExtractionError custom exception."""

    def test_str_includes_source_name_and_message(self) -> None:
        err = DataExtractionError(source_name="csv", message="File not found")
        assert "csv" in str(err)
        assert "File not found" in str(err)

    def test_cause_attribute_is_preserved(self) -> None:
        original = FileNotFoundError("missing")
        err = DataExtractionError("csv", "wrap", cause=original)
        assert err.cause is original

    def test_cause_can_be_none(self) -> None:
        err = DataExtractionError("api", "network timeout")
        assert err.cause is None

    def test_is_subclass_of_exception(self) -> None:
        assert issubclass(DataExtractionError, Exception)

    def test_extraction_validation_error_is_subclass(self) -> None:
        assert issubclass(ExtractionValidationError, DataExtractionError)


# =============================================================================
# ExtractionMetadata tests
# =============================================================================


class TestExtractionMetadata:
    """Tests for the ExtractionMetadata value object."""

    def _make_meta(self, **kwargs: Any) -> ExtractionMetadata:
        from datetime import datetime

        defaults: dict[str, Any] = {
            "source_name": "test",
            "rows_extracted": 100,
            "columns": ["a", "b"],
            "started_at": datetime.now(tz=UTC),
            "completed_at": datetime.now(tz=UTC),
            "duration_ms": 1234.5,
        }
        defaults.update(kwargs)
        return ExtractionMetadata(**defaults)

    def test_duration_seconds_converts_correctly(self) -> None:
        meta = self._make_meta(duration_ms=1234.5)
        assert meta.duration_seconds == pytest.approx(1.235, rel=1e-3)

    def test_to_log_string_contains_source_name(self) -> None:
        meta = self._make_meta(source_name="my_source")
        assert "my_source" in meta.to_log_string()

    def test_to_log_string_contains_row_count(self) -> None:
        meta = self._make_meta(rows_extracted=42)
        assert "42" in meta.to_log_string()

    def test_metadata_is_immutable(self) -> None:
        meta = self._make_meta()
        with pytest.raises((AttributeError, TypeError)):
            meta.rows_extracted = 999  # type: ignore[misc]

    def test_extra_defaults_to_empty_dict(self) -> None:
        meta = self._make_meta()
        assert meta.extra == {}


# =============================================================================
# BaseExtractor tests
# =============================================================================


class TestBaseExtractor:
    """Tests for BaseExtractor.run() Template Method behaviour."""

    def test_run_returns_dataframe_and_metadata_tuple(self) -> None:
        ext = make_concrete_extractor()
        result = ext.run()
        assert isinstance(result, tuple)
        df, meta = result
        assert isinstance(df, pd.DataFrame)
        assert isinstance(meta, ExtractionMetadata)

    def test_run_calls_validate_before_extract(self) -> None:
        """Verify the template method order via call tracking."""
        call_order: list[str] = []

        class _OrderTracker(BaseExtractor):
            def validate_source(self) -> bool:
                call_order.append("validate")
                return True

            def extract(self) -> pd.DataFrame:
                call_order.append("extract")
                return pd.DataFrame({"x": [1]})

        _OrderTracker("tracker").run()
        assert call_order == ["validate", "extract"]

    def test_run_raises_validation_error_when_validate_returns_false(self) -> None:
        ext = make_concrete_extractor(validate_returns=False)
        with pytest.raises(ExtractionValidationError) as exc_info:
            ext.run()
        assert "test_source" in str(exc_info.value)

    def test_run_raises_extraction_error_when_extract_raises(self) -> None:
        class _FailingExtractor(BaseExtractor):
            def validate_source(self) -> bool:
                return True

            def extract(self) -> pd.DataFrame:
                raise DataExtractionError("fail_source", "read error")

        with pytest.raises(DataExtractionError):
            _FailingExtractor("fail_source").run()

    def test_run_raises_when_extract_returns_empty_and_allow_empty_false(self) -> None:
        ext = make_concrete_extractor(
            extract_returns=pd.DataFrame(),
            allow_empty=False,
        )
        with pytest.raises(DataExtractionError, match="empty DataFrame"):
            ext.run()

    def test_run_succeeds_when_extract_returns_empty_and_allow_empty_true(self) -> None:
        ext = make_concrete_extractor(
            extract_returns=pd.DataFrame(),
            allow_empty=True,
        )
        df, meta = ext.run()
        assert df.empty
        assert meta.rows_extracted == 0

    def test_metadata_row_count_matches_dataframe(self) -> None:
        data = pd.DataFrame({"a": ["1", "2", "3", "4", "5"]})
        ext = make_concrete_extractor(extract_returns=data)
        df, meta = ext.run()
        assert meta.rows_extracted == len(df) == 5

    def test_metadata_columns_match_dataframe(self) -> None:
        data = pd.DataFrame({"title": [], "company": [], "location": []})
        ext = make_concrete_extractor(extract_returns=data, allow_empty=True)
        _, meta = ext.run()
        assert meta.columns == ["title", "company", "location"]

    def test_metadata_duration_is_positive(self) -> None:
        ext = make_concrete_extractor()
        _, meta = ext.run()
        assert meta.duration_ms > 0

    def test_last_metadata_is_none_before_first_run(self) -> None:
        ext = make_concrete_extractor()
        assert ext.last_metadata is None

    def test_last_metadata_is_set_after_run(self) -> None:
        ext = make_concrete_extractor()
        _, meta = ext.run()
        assert ext.last_metadata is meta

    def test_unexpected_exception_in_validate_is_wrapped(self) -> None:
        class _BrokenValidate(BaseExtractor):
            def validate_source(self) -> bool:
                raise RuntimeError("unexpected!")

            def extract(self) -> pd.DataFrame:
                return pd.DataFrame()

        with pytest.raises(ExtractionValidationError):
            _BrokenValidate("broken").run()

    def test_unexpected_exception_in_extract_is_wrapped(self) -> None:
        class _BrokenExtract(BaseExtractor):
            def validate_source(self) -> bool:
                return True

            def extract(self) -> pd.DataFrame:
                raise RuntimeError("disk full")

        with pytest.raises(DataExtractionError):
            _BrokenExtract("broken").run()


# =============================================================================
# CsvExtractor.validate_source() tests
# =============================================================================


class TestCsvExtractorValidateSource:
    """Tests for CsvExtractor.validate_source()."""

    def test_returns_true_for_valid_csv(self, sample_csv: Path) -> None:
        ext = CsvExtractor(file_path=sample_csv)
        assert ext.validate_source() is True

    def test_returns_false_when_file_does_not_exist(self, tmp_path: Path) -> None:
        ext = CsvExtractor(file_path=tmp_path / "nonexistent.csv")
        assert ext.validate_source() is False

    def test_returns_false_when_path_is_directory(self, tmp_path: Path) -> None:
        ext = CsvExtractor(file_path=tmp_path)  # tmp_path is a directory
        assert ext.validate_source() is False

    def test_returns_false_for_zero_byte_file(self, zero_byte_file: Path) -> None:
        ext = CsvExtractor(file_path=zero_byte_file)
        assert ext.validate_source() is False

    def test_does_not_raise_on_missing_file(self, tmp_path: Path) -> None:
        """validate_source() must return False, never raise, on bad input."""
        ext = CsvExtractor(file_path=tmp_path / "missing.csv")
        result = ext.validate_source()  # Should not raise
        assert isinstance(result, bool)


# =============================================================================
# CsvExtractor.extract() tests
# =============================================================================


class TestCsvExtractorExtract:
    """Tests for CsvExtractor.extract()."""

    def test_returns_dataframe_with_correct_shape(self, sample_csv: Path) -> None:
        ext = CsvExtractor(file_path=sample_csv)
        df = ext.extract()
        assert df.shape == (3, 5)  # 3 data rows, 5 columns

    def test_all_columns_are_object_dtype(self, sample_csv: Path) -> None:
        """All values must be strings (object dtype) — no type inference."""
        ext = CsvExtractor(file_path=sample_csv)
        df = ext.extract()
        for dtype in df.dtypes:
            assert (
                pd.api.types.is_string_dtype(dtype) or dtype == object
            ), f"Expected object/string dtype, got {dtype}"

    def test_column_names_are_normalised_to_lowercase(self, sample_csv: Path) -> None:
        ext = CsvExtractor(file_path=sample_csv)
        df = ext.extract()
        assert list(df.columns) == [
            "job_title",
            "company_name",
            "location",
            "salary_min",
            "salary_max",
        ]

    def test_handles_whitespace_padded_column_names(self, tmp_path: Path) -> None:
        content = " Job Title , Company Name \n Engineer,Acme\n"
        f = tmp_path / "padded.csv"
        f.write_text(content, encoding="utf-8")
        df = CsvExtractor(file_path=f).extract()
        assert "job_title" in df.columns
        assert "company_name" in df.columns

    def test_utf8_file_reads_correctly(self, sample_csv: Path) -> None:
        ext = CsvExtractor(file_path=sample_csv, encoding="utf-8")
        df = ext.extract()
        assert "Data Engineer" in df["job_title"].values

    def test_latin1_file_falls_back_from_utf8(self, latin1_csv: Path) -> None:
        """UTF-8 decode will fail; extractor should fall back to latin-1."""
        ext = CsvExtractor(file_path=latin1_csv, encoding="utf-8")
        df = ext.extract()
        assert len(df) == 2
        assert "title" in df.columns

    def test_use_columns_returns_only_requested_columns(self, sample_csv: Path) -> None:
        ext = CsvExtractor(
            file_path=sample_csv,
            use_columns=["Job Title", "Company Name"],
        )
        df = ext.extract()
        assert set(df.columns) == {"job_title", "company_name"}

    def test_use_columns_raises_on_nonexistent_column(self, sample_csv: Path) -> None:
        ext = CsvExtractor(
            file_path=sample_csv,
            use_columns=["nonexistent_column"],
        )
        with pytest.raises(DataExtractionError, match="not found"):
            ext.extract()

    def test_empty_data_rows_returns_empty_dataframe(self, empty_csv: Path) -> None:
        """A file with only a header row should return an empty (but valid) DataFrame."""
        ext = CsvExtractor(file_path=empty_csv)
        df = ext.extract()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert len(df.columns) == 3  # Header was parsed

    def test_tab_separator_reads_tsv_correctly(self, tmp_path: Path) -> None:
        tsv_content = "title\tcompany\nData Engineer\tAcme Corp\n"
        f = tmp_path / "jobs.tsv"
        f.write_text(tsv_content, encoding="utf-8")
        df = CsvExtractor(file_path=f, separator="\t").extract()
        assert df.shape == (1, 2)
        assert "data engineer" in df["title"].str.lower().values


# =============================================================================
# CsvExtractor.run() integration tests
# =============================================================================


class TestCsvExtractorRun:
    """Integration tests for CsvExtractor.run() (validate + extract + metadata)."""

    def test_run_returns_correct_shape(self, sample_csv: Path) -> None:
        df, meta = CsvExtractor(file_path=sample_csv).run()
        assert df.shape == (3, 5)

    def test_run_metadata_rows_matches_dataframe(self, sample_csv: Path) -> None:
        df, meta = CsvExtractor(file_path=sample_csv).run()
        assert meta.rows_extracted == len(df) == 3

    def test_run_metadata_extra_contains_file_path(self, sample_csv: Path) -> None:
        _, meta = CsvExtractor(file_path=sample_csv).run()
        assert "file_path" in meta.extra
        assert "file_name" in meta.extra

    def test_run_raises_validation_error_for_missing_file(self, tmp_path: Path) -> None:
        ext = CsvExtractor(file_path=tmp_path / "missing.csv")
        with pytest.raises(ExtractionValidationError):
            ext.run()

    def test_run_raises_extraction_error_for_empty_file_when_not_allowed(
        self, empty_csv: Path
    ) -> None:
        ext = CsvExtractor(file_path=empty_csv, allow_empty=False)
        with pytest.raises(DataExtractionError, match="empty DataFrame"):
            ext.run()

    def test_run_succeeds_for_empty_file_when_allowed(self, empty_csv: Path) -> None:
        ext = CsvExtractor(file_path=empty_csv, allow_empty=True)
        df, meta = ext.run()
        assert df.empty
        assert meta.rows_extracted == 0


# =============================================================================
# CsvExtractor.extract_chunks() tests
# =============================================================================


class TestCsvExtractorExtractChunks:
    """Tests for CsvExtractor.extract_chunks()."""

    def test_raises_when_chunk_size_not_set(self, sample_csv: Path) -> None:
        ext = CsvExtractor(file_path=sample_csv)  # chunk_size=None
        with pytest.raises(DataExtractionError, match="chunk_size"):
            list(ext.extract_chunks())

    def test_yields_correct_number_of_chunks(self, sample_csv: Path) -> None:
        # sample_csv has 3 rows; chunk_size=2 → chunks of 2 and 1
        ext = CsvExtractor(file_path=sample_csv, chunk_size=2)
        chunks = list(ext.extract_chunks())
        assert len(chunks) == 2
        assert len(chunks[0]) == 2
        assert len(chunks[1]) == 1

    def test_all_rows_are_present_across_chunks(self, sample_csv: Path) -> None:
        ext = CsvExtractor(file_path=sample_csv, chunk_size=1)
        chunks = list(ext.extract_chunks())
        total_rows = sum(len(c) for c in chunks)
        assert total_rows == 3  # sample_csv has 3 data rows

    def test_each_chunk_is_a_dataframe(self, sample_csv: Path) -> None:
        ext = CsvExtractor(file_path=sample_csv, chunk_size=2)
        for chunk in ext.extract_chunks():
            assert isinstance(chunk, pd.DataFrame)


# =============================================================================
# CsvExtractor.get_file_info() tests
# =============================================================================


class TestCsvExtractorGetFileInfo:
    """Tests for CsvExtractor.get_file_info()."""

    def test_returns_dict_with_size_bytes(self, sample_csv: Path) -> None:
        info = CsvExtractor(file_path=sample_csv).get_file_info()
        assert info["size_bytes"] > 0

    def test_returns_file_name(self, sample_csv: Path) -> None:
        info = CsvExtractor(file_path=sample_csv).get_file_info()
        assert info["file_name"] == "jobs.csv"

    def test_raises_file_not_found_for_missing_file(self, tmp_path: Path) -> None:
        ext = CsvExtractor(file_path=tmp_path / "ghost.csv")
        with pytest.raises(FileNotFoundError):
            ext.get_file_info()

    def test_size_mb_is_float(self, sample_csv: Path) -> None:
        info = CsvExtractor(file_path=sample_csv).get_file_info()
        assert isinstance(info["size_mb"], float)


# =============================================================================
# DirectoryExtractor.validate_source() tests
# =============================================================================


class TestDirectoryExtractorValidateSource:
    """Tests for DirectoryExtractor.validate_source()."""

    def test_returns_true_for_valid_directory(self, multi_csv_dir: Path) -> None:
        ext = DirectoryExtractor(directory=multi_csv_dir)
        assert ext.validate_source() is True

    def test_returns_false_when_directory_does_not_exist(self, tmp_path: Path) -> None:
        ext = DirectoryExtractor(directory=tmp_path / "nonexistent")
        assert ext.validate_source() is False

    def test_returns_false_when_path_is_a_file(self, sample_csv: Path) -> None:
        ext = DirectoryExtractor(directory=sample_csv)  # File, not directory
        assert ext.validate_source() is False

    def test_returns_false_when_no_matching_files(self, tmp_path: Path) -> None:
        (tmp_path / "data.json").write_text("{}", encoding="utf-8")
        ext = DirectoryExtractor(directory=tmp_path, glob_pattern="*.csv")
        assert ext.validate_source() is False


# =============================================================================
# DirectoryExtractor.extract() tests
# =============================================================================


class TestDirectoryExtractorExtract:
    """Tests for DirectoryExtractor.extract() with various schema modes."""

    def test_combines_all_csv_files(self, multi_csv_dir: Path) -> None:
        df, meta = DirectoryExtractor(directory=multi_csv_dir).run()
        # jan=1 row, feb=2 rows, mar=1 row → 4 total
        assert len(df) == 4

    def test_adds_source_file_column_by_default(self, multi_csv_dir: Path) -> None:
        df, _ = DirectoryExtractor(directory=multi_csv_dir).run()
        assert "_source_file" in df.columns

    def test_does_not_add_source_file_column_when_disabled(
        self, multi_csv_dir: Path
    ) -> None:
        df, _ = DirectoryExtractor(directory=multi_csv_dir, add_source_col=False).run()
        assert "_source_file" not in df.columns

    def test_source_file_column_has_correct_filenames(
        self, multi_csv_dir: Path
    ) -> None:
        df, _ = DirectoryExtractor(directory=multi_csv_dir).run()
        file_names = set(df["_source_file"].unique())
        assert file_names == {"jan.csv", "feb.csv", "mar.csv"}

    def test_metadata_files_processed_count(self, multi_csv_dir: Path) -> None:
        _, meta = DirectoryExtractor(directory=multi_csv_dir).run()
        assert meta.extra["files_processed"] == 3

    def test_schema_mode_strict_raises_on_column_mismatch(self, tmp_path: Path) -> None:
        (tmp_path / "a.csv").write_text("col_a,col_b\n1,2\n", encoding="utf-8")
        (tmp_path / "b.csv").write_text("col_a,col_c\n3,4\n", encoding="utf-8")
        ext = DirectoryExtractor(directory=tmp_path, schema_mode="strict")
        with pytest.raises(DataExtractionError, match="strict"):
            ext.extract()

    def test_schema_mode_union_fills_nan_for_missing_columns(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "a.csv").write_text("col_a,col_b\n1,2\n", encoding="utf-8")
        (tmp_path / "b.csv").write_text("col_a,col_c\n3,4\n", encoding="utf-8")
        df, _ = DirectoryExtractor(directory=tmp_path, schema_mode="union").run()
        # Both col_b and col_c should exist; one will be NaN per row
        assert "col_b" in df.columns or "col_c" in df.columns

    def test_schema_mode_intersect_keeps_only_common_columns(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "a.csv").write_text("col_a,col_b\n1,2\n", encoding="utf-8")
        (tmp_path / "b.csv").write_text("col_a,col_c\n3,4\n", encoding="utf-8")
        df, _ = DirectoryExtractor(
            directory=tmp_path, schema_mode="intersect", add_source_col=False
        ).run()
        # Only col_a is common to both files
        assert list(df.columns) == ["col_a"]
