"""jobpulse.utils.file_utils — File and directory utility functions.

Provides pathlib-based helpers for safe file and directory operations.
All functions use pathlib.Path (never os.path).

Functions:
    ensure_directory()    → Create a directory tree if it doesn't exist
    resolve_project_root() → Locate the project root directory
    list_files()          → List files in a directory with optional filtering
    archive_file()        → Move a file to the archive directory with timestamp

Usage:
    >>> from jobpulse.utils.file_utils import ensure_directory
    >>> path = ensure_directory(Path("data/staging/2024-01"))
    >>> path.exists()
    True
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def ensure_directory(path: Path) -> Path:
    """Create a directory (and all parent directories) if it doesn't exist.

    This is the pathlib equivalent of ``os.makedirs(exist_ok=True)``.

    Args:
        path: The directory path to create.

    Returns:
        Path: The same path, guaranteed to exist after this call.

    Example:
        >>> ensure_directory(Path("data/staging/batch_001"))
        PosixPath('data/staging/batch_001')
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_project_root() -> Path:
    """Resolve the absolute path to the project root directory.

    Finds the root by traversing up from this file until a directory
    containing pyproject.toml is found.

    Returns:
        Path: Absolute path to the project root.

    Raises:
        FileNotFoundError: If pyproject.toml cannot be found in any parent.

    Example:
        >>> root = resolve_project_root()
        >>> (root / "pyproject.toml").exists()
        True
    """
    current = Path(__file__).resolve()
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    raise FileNotFoundError(
        "Could not locate project root (no pyproject.toml found). "
        "Run this from within the jobpulse project directory."
    )


def list_files(
    directory: Path,
    pattern: str = "*",
    recursive: bool = False,
) -> list[Path]:
    """List all files in a directory matching a glob pattern.

    Args:
        directory: The directory to search.
        pattern:   Glob pattern to filter files (e.g., '*.csv').
                   Defaults to '*' (all files).
        recursive: If True, search subdirectories recursively.
                   Defaults to False.

    Returns:
        list[Path]: Sorted list of matching file paths.

    Raises:
        NotADirectoryError: If ``directory`` is not a valid directory.

    Example:
        >>> files = list_files(Path("data/raw"), pattern="*.csv")
        >>> [f.name for f in files]
        ['jobs_2024_01.csv', 'jobs_2024_02.csv']
    """
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    glob_fn = directory.rglob if recursive else directory.glob
    return sorted(p for p in glob_fn(pattern) if p.is_file())


def archive_file(source_path: Path, archive_dir: Path) -> Path:
    """Move a file to the archive directory with a UTC timestamp suffix.

    The destination filename format:
        <stem>_<YYYYMMDD_HHMMSS><suffix>

    Example:
        jobs_raw.csv  →  archive/jobs_raw_20240115_143022.csv

    Args:
        source_path: Path to the file to be archived.
        archive_dir: Destination directory for the archived file.

    Returns:
        Path: Path to the archived file in the archive directory.

    Raises:
        FileNotFoundError: If source_path does not exist.

    Example:
        >>> archived = archive_file(
        ...     source_path=Path("data/raw/jobs.csv"),
        ...     archive_dir=Path("data/archive"),
        ... )
    """
    if not source_path.exists():
        raise FileNotFoundError(f"File not found: {source_path}")

    ensure_directory(archive_dir)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    destination = archive_dir / f"{source_path.stem}_{timestamp}{source_path.suffix}"

    source_path.rename(destination)
    return destination
