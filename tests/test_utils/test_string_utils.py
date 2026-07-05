"""
tests/test_utils/test_string_utils.py — Unit tests for string utility functions.

These are pure unit tests — no database, no filesystem, no network required.
They should run in milliseconds.

Coverage targets:
    - clean_text()
    - normalise_job_title()
    - slugify()
    - extract_salary_number()
"""

from __future__ import annotations

import pytest

from jobpulse.utils.string_utils import (
    clean_text,
    extract_salary_number,
    normalise_job_title,
    slugify,
)


class TestCleanText:
    """Tests for clean_text()."""

    def test_strips_leading_and_trailing_whitespace(self) -> None:
        """clean_text should strip leading and trailing spaces."""
        assert clean_text("  hello  ") == "hello"

    def test_collapses_internal_whitespace(self) -> None:
        """clean_text should collapse multiple internal spaces to one."""
        assert clean_text("data  engineer") == "data engineer"

    def test_returns_none_for_none_input(self) -> None:
        """clean_text(None) should return None."""
        assert clean_text(None) is None

    def test_returns_none_for_whitespace_only_string(self) -> None:
        """clean_text('   ') should return None."""
        assert clean_text("   ") is None

    def test_handles_tabs_and_newlines(self) -> None:
        """clean_text should handle tab and newline characters."""
        assert clean_text("data\t engineer\n") == "data engineer"


class TestNormaliseJobTitle:
    """Tests for normalise_job_title()."""

    def test_maps_data_engineer_variants(self) -> None:
        """Common 'data engineer' variants should map to 'Data Engineer'."""
        assert normalise_job_title("data engineer") == "Data Engineer"
        assert normalise_job_title("etl developer") == "Data Engineer"

    def test_maps_data_scientist_variants(self) -> None:
        """Common 'data scientist' variants should map to 'Data Scientist'."""
        assert normalise_job_title("machine learning engineer") == "Data Scientist"

    def test_returns_cleaned_original_for_unknown_titles(self) -> None:
        """Unknown titles should return the cleaned original string."""
        result = normalise_job_title("  quantum computing specialist  ")
        assert result == "Quantum Computing Specialist"

    def test_returns_none_for_none_input(self) -> None:
        """normalise_job_title(None) should return None."""
        assert normalise_job_title(None) is None


class TestSlugify:
    """Tests for slugify()."""

    def test_converts_spaces_to_hyphens(self) -> None:
        """Spaces should become hyphens."""
        assert slugify("data engineer") == "data-engineer"

    def test_lowercases_output(self) -> None:
        """Output should be all lowercase."""
        assert slugify("Data Engineer") == "data-engineer"

    def test_removes_special_characters(self) -> None:
        """Parentheses and punctuation should be removed."""
        assert slugify("Senior Data Engineer (Remote)") == "senior-data-engineer-remote"

    def test_handles_consecutive_spaces(self) -> None:
        """Multiple spaces should collapse to a single hyphen."""
        assert slugify("data  engineer") == "data-engineer"


class TestExtractSalaryNumber:
    """Tests for extract_salary_number()."""

    def test_parses_dollar_k_format(self) -> None:
        """$90k should parse to 90000.0."""
        assert extract_salary_number("$90k") == pytest.approx(90000.0)

    def test_parses_dollar_number_format(self) -> None:
        """$120,000 should parse to 120000.0."""
        assert extract_salary_number("$120,000") == pytest.approx(120000.0)

    def test_parses_pound_format(self) -> None:
        """£75,000 should parse to 75000.0."""
        assert extract_salary_number("£75,000") == pytest.approx(75000.0)

    def test_returns_none_for_none_input(self) -> None:
        """extract_salary_number(None) should return None."""
        assert extract_salary_number(None) is None

    def test_returns_none_for_non_numeric_string(self) -> None:
        """Non-numeric strings like 'Competitive' should return None."""
        assert extract_salary_number("Competitive") is None

    def test_parses_plain_integer_string(self) -> None:
        """Plain integer strings like '90000' should parse correctly."""
        assert extract_salary_number("90000") == pytest.approx(90000.0)
