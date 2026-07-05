"""
tests/test_utils/test_file_utils.py — Unit tests for file utility functions.

Tests:
    - ensure_directory() creates nested directories
    - ensure_directory() is idempotent (safe to call twice)
    - resolve_project_root() finds pyproject.toml
    - list_files() returns correct file list
    - archive_file() moves file with timestamp suffix
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jobpulse.utils.file_utils import (
    archive_file,
    ensure_directory,
    list_files,
    resolve_project_root,
)


class TestEnsureDirectory:
    """Tests for ensure_directory()."""

    def test_creates_directory_if_not_exists(self, tmp_path: Path) -> None:
        """Should create a new directory and all parent directories."""
        target = tmp_path / "a" / "b" / "c"
        result = ensure_directory(target)
        assert result.exists()
        assert result.is_dir()

    def test_returns_the_path(self, tmp_path: Path) -> None:
        """Should return the same path it created."""
        target = tmp_path / "new_dir"
        result = ensure_directory(target)
        assert result == target

    def test_is_idempotent(self, tmp_path: Path) -> None:
        """Calling twice on an existing directory should not raise."""
        target = tmp_path / "existing"
        ensure_directory(target)
        ensure_directory(target)  # Should not raise
        assert target.exists()


class TestResolveProjectRoot:
    """Tests for resolve_project_root()."""

    def test_finds_project_root(self) -> None:
        """Should return a directory containing pyproject.toml."""
        root = resolve_project_root()
        assert (root / "pyproject.toml").exists()

    def test_returns_path_object(self) -> None:
        """Return type should be pathlib.Path."""
        root = resolve_project_root()
        assert isinstance(root, Path)


class TestListFiles:
    """Tests for list_files()."""

    def test_lists_files_in_directory(self, tmp_path: Path) -> None:
        """Should return all files in a flat directory."""
        (tmp_path / "a.csv").touch()
        (tmp_path / "b.csv").touch()
        files = list_files(tmp_path)
        assert len(files) == 2

    def test_filters_by_pattern(self, tmp_path: Path) -> None:
        """Should respect glob pattern filter."""
        (tmp_path / "data.csv").touch()
        (tmp_path / "config.yaml").touch()
        csv_files = list_files(tmp_path, pattern="*.csv")
        assert len(csv_files) == 1
        assert csv_files[0].name == "data.csv"

    def test_raises_for_non_directory(self, tmp_path: Path) -> None:
        """Should raise NotADirectoryError for a file path."""
        file_path = tmp_path / "test.txt"
        file_path.touch()
        with pytest.raises(NotADirectoryError):
            list_files(file_path)

    def test_returns_sorted_list(self, tmp_path: Path) -> None:
        """Results should be sorted alphabetically."""
        (tmp_path / "c.csv").touch()
        (tmp_path / "a.csv").touch()
        (tmp_path / "b.csv").touch()
        files = list_files(tmp_path, pattern="*.csv")
        names = [f.name for f in files]
        assert names == sorted(names)


class TestArchiveFile:
    """Tests for archive_file()."""

    def test_moves_file_to_archive_directory(self, tmp_path: Path) -> None:
        """Source file should be moved to the archive directory."""
        source = tmp_path / "jobs.csv"
        source.touch()
        archive_dir = tmp_path / "archive"

        archived = archive_file(source, archive_dir)

        assert archived.exists()
        assert not source.exists()
        assert archived.parent == archive_dir

    def test_archived_filename_contains_timestamp(self, tmp_path: Path) -> None:
        """Archived filename should contain a timestamp suffix."""
        source = tmp_path / "jobs.csv"
        source.touch()
        archive_dir = tmp_path / "archive"

        archived = archive_file(source, archive_dir)

        # Filename should be like: jobs_20240115_103000.csv
        assert archived.stem.startswith("jobs_")
        assert archived.suffix == ".csv"

    def test_raises_for_missing_source_file(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError if source file doesn't exist."""
        source = tmp_path / "nonexistent.csv"
        with pytest.raises(FileNotFoundError):
            archive_file(source, tmp_path / "archive")
