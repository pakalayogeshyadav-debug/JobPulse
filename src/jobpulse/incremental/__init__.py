"""jobpulse.incremental — Incremental ETL package.

Replaces the full-reload pattern with a change-aware pipeline that:

    1. Reads the watermark for each source (last successful load timestamp).
    2. Filters the incoming DataFrame to only rows that arrived after
       (watermark - late_arrival_buffer).
    3. Classifies each row as NEW | UPDATED | UNCHANGED via content hashing.
    4. UPSERTs only NEW and UPDATED rows — UNCHANGED rows are skipped entirely.
    5. Advances the watermark to the current run timestamp on success.

Public API:
    WatermarkStore          — abstract interface for watermark persistence
    PostgresWatermarkStore  — PostgreSQL-backed implementation
    InMemoryWatermarkStore  — in-memory implementation (tests)
    ChangeDetector          — classifies rows by comparing against DB state
    IncrementalLoader       — UPSERT wrapper that tracks change classification
    IncrementalRunner       — end-to-end orchestrator
    WatermarkRecord         — value object for one watermark entry
    ChangeClassification    — enum: NEW | UPDATED | UNCHANGED
    IncrementalLoadResult   — immutable load result with change breakdown
"""

from jobpulse.incremental.change_detector import (
    ChangeClassification,
    ChangeDetectionResult,
    ChangeDetector,
    RowChange,
)
from jobpulse.incremental.loader import (
    IncrementalLoader,
    IncrementalLoadResult,
)
from jobpulse.incremental.runner import IncrementalRunner
from jobpulse.incremental.watermark import (
    AbstractWatermarkStore,
    InMemoryWatermarkStore,
    PostgresWatermarkStore,
    WatermarkRecord,
)

__all__ = [
    # Watermark
    "WatermarkRecord",
    "AbstractWatermarkStore",
    "PostgresWatermarkStore",
    "InMemoryWatermarkStore",
    # Change detection
    "ChangeClassification",
    "RowChange",
    "ChangeDetectionResult",
    "ChangeDetector",
    # Loading
    "IncrementalLoadResult",
    "IncrementalLoader",
    # Orchestration
    "IncrementalRunner",
]
