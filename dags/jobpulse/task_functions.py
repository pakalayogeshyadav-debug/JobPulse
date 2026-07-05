"""
dags/jobpulse/task_functions.py — Pure Python callable functions for Airflow tasks.

Every function here is a self-contained Python callable that Airflow's
@task decorator (TaskFlow API) or PythonOperator will invoke.

Design Principles:
    1. PURE CALLABLES — No Airflow imports inside the function body.
       Functions must work without Airflow installed (unit-testable in isolation).

    2. XCOM-DRIVEN STATE — Tasks communicate via Airflow's XCom mechanism.
       Each task returns a serialisable dict (not a DataFrame) that the next
       task receives as its input. DataFrames are written to disk (Parquet)
       and the file path is passed via XCom — this avoids XCom size limits
       (XCom is stored in the Airflow metadata database, limited to ~48KB by default).

    3. IDEMPOTENT — Every task can be safely re-run. Extracts check data source
       timestamps; loads use UPSERT (ON CONFLICT DO UPDATE). Running the same
       DAG run twice produces the same result.

    4. SINGLE RESPONSIBILITY — Each function does exactly one thing.
       No function spans multiple ETL stages. This makes retries surgical:
       if Transform fails, only Transform re-runs — not Extract.

    5. STRUCTURED LOGGING — Every function logs its inputs, outputs, and
       timing. Airflow captures all stdout/stderr — structured logs appear
       in the Airflow task log viewer.

XCom Payload Schema:
    All tasks that produce data return a dict matching this schema:
    {
        "status":       "success" | "skipped" | "partial",
        "rows":         int,           # rows produced
        "duration_s":   float,         # wall-clock seconds
        "parquet_path": str | None,    # absolute path to Parquet file (if applicable)
        "source_name":  str,           # data source identifier
        "warnings":     list[str],     # non-fatal issues
        "metadata":     dict,          # additional context
    }
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ensure jobpulse package is importable inside the Airflow worker.
# In a real deployment, install the package: pip install -e /path/to/jobpulse
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# Airflow writes task temp files here; override via AIRFLOW_HOME env var.
_STAGING_DIR = Path(os.getenv("JOBPULSE_STAGING_DIR", str(_PROJECT_ROOT / "data" / "staging")))
_STAGING_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Helper: staging file path
# =============================================================================

def _staging_path(run_id: str, stage: str, source: str) -> Path:
    """
    Construct a deterministic staging Parquet file path for a given run.

    Using run_id in the path makes each DAG run's staging files independent —
    concurrent DAG runs won't overwrite each other's data.

    Args:
        run_id:  Airflow DAG run ID (unique per execution).
        stage:   Pipeline stage name ('extracted', 'validated', 'transformed').
        source:  Data source name ('csv', 'adzuna', 'usajobs').

    Returns:
        Path: Absolute path to the staging Parquet file.
    """
    # Sanitise run_id: Airflow run IDs contain colons which are illegal on Windows
    safe_run_id = run_id.replace(":", "_").replace("+", "_")
    path = _STAGING_DIR / safe_run_id / stage / f"{source}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# =============================================================================
# TASK 1: check_source_availability
# =============================================================================

def check_source_availability(source_name: str, source_config: dict) -> dict:
    """
    Pre-flight check: verify the data source is accessible before extraction starts.

    This is a lightweight sensor-style task that runs BEFORE the main extract.
    If it fails, the pipeline aborts immediately with a clear error — no wasted
    compute on extraction tasks that will certainly fail.

    WHY a separate task (not merged into extract)?
        Airflow's retry policy applies per-task. Source availability checks
        should retry fast (e.g., 5× with 30s delay) because the issue is likely
        transient (API rate limit, network blip). The extract task might need
        different retry settings (e.g., 3× with 5-minute delay because it's slow).
        Separating them gives independent retry control.

    Args:
        source_name:   Machine-readable source identifier.
        source_config: Source configuration dict (path, url, credentials, etc.).

    Returns:
        dict: XCom payload with availability status.

    Raises:
        RuntimeError: If the source is not accessible after all retries.
    """
    from jobpulse.extraction.base import ExtractionValidationError
    from jobpulse.extraction.csv_extractor import CsvExtractor

    logger.info("Pre-flight source check | source=%s", source_name)
    t0 = time.perf_counter()

    try:
        if source_config.get("type") == "csv":
            extractor = CsvExtractor(file_path=Path(source_config["path"]))
        else:
            # Future: ApiExtractor, S3Extractor, etc.
            raise NotImplementedError(
                f"Source type '{source_config.get('type')}' not yet supported."
            )

        is_ok = extractor.validate_source()
        duration = time.perf_counter() - t0

        if not is_ok:
            raise RuntimeError(
                f"Source '{source_name}' is not accessible. "
                f"Config: {source_config}"
            )

        logger.info(
            "Source check PASSED | source=%s | duration=%.2fs",
            source_name, duration,
        )
        return {
            "status": "success",
            "source_name": source_name,
            "duration_s": round(duration, 3),
            "rows": 0,
            "parquet_path": None,
            "warnings": [],
            "metadata": {"source_config": source_config},
        }

    except ExtractionValidationError as exc:
        logger.error("Source check FAILED | source=%s | error=%s", source_name, exc)
        raise RuntimeError(f"Source '{source_name}' unavailable: {exc}") from exc


# =============================================================================
# TASK 2: extract_data
# =============================================================================

def extract_data(
    source_name: str,
    source_config: dict,
    run_id: str,
) -> dict:
    """
    Extract raw job market data from the configured source.

    Saves the extracted DataFrame to Parquet on the shared staging directory.
    Returns the file path via XCom — not the DataFrame itself.

    WHY Parquet (not CSV)?
        Parquet is columnar, compressed, and preserves dtypes.
        CSV would re-infer all types and expand file size by 3-5×.
        XCom can only hold small payloads; Parquet on shared disk handles large data.

    WHY shared disk (not object storage)?
        For local/small-scale deployment, shared disk (NFS or same machine) is
        simpler. For production on Kubernetes, replace with S3-backed staging:
        change _staging_path() to return an s3:// URI and add boto3 I/O.

    Args:
        source_name:   Source identifier.
        source_config: Source configuration dict.
        run_id:        Airflow run ID (used to build the staging path).

    Returns:
        dict: XCom payload containing row count and Parquet file path.

    Raises:
        RuntimeError: If extraction fails (triggers Airflow retry).
    """
    from jobpulse.extraction.base import DataExtractionError
    from jobpulse.extraction.csv_extractor import CsvExtractor

    logger.info("EXTRACT START | source=%s | run=%s", source_name, run_id)
    t0 = time.perf_counter()
    warnings: list[str] = []

    try:
        if source_config.get("type") == "csv":
            extractor = CsvExtractor(file_path=Path(source_config["path"]))
        else:
            raise NotImplementedError(
                f"Source type '{source_config.get('type')}' not yet supported."
            )

        df, meta = extractor.run()

        # Persist to staging Parquet
        parquet_path = _staging_path(run_id, "extracted", source_name)
        df.to_parquet(parquet_path, index=False, compression="snappy")

        duration = time.perf_counter() - t0
        logger.info(
            "EXTRACT COMPLETE | source=%s | rows=%d | file=%s | duration=%.2fs",
            source_name, len(df), parquet_path, duration,
        )

        return {
            "status": "success",
            "source_name": source_name,
            "rows": len(df),
            "duration_s": round(duration, 3),
            "parquet_path": str(parquet_path),
            "warnings": warnings,
            "metadata": {
                "columns": list(df.columns),
                "extraction_duration_ms": meta.duration_ms,
            },
        }

    except DataExtractionError as exc:
        logger.error(
            "EXTRACT FAILED | source=%s | error=%s", source_name, exc
        )
        raise RuntimeError(
            f"Extraction failed for source '{source_name}': {exc}"
        ) from exc


# =============================================================================
# TASK 3: validate_data
# =============================================================================

def validate_data(
    extract_result: dict,
    run_id: str,
    max_null_threshold_pct: float = 30.0,
    min_rows: int = 1,
) -> dict:
    """
    Validate the extracted DataFrame for structural and quality requirements.

    Validation rules applied:
        1. Row count >= min_rows (configurable, default 1)
        2. Required columns present (source-specific schema check)
        3. Critical columns (job_title, company_name) not >max_null_threshold_pct% null
        4. No fully-duplicate rows (quick exact dedup check)

    WHY validate before transform (not during)?
        The transformer handles recoverable quality issues (bad salary strings,
        non-standard dates). Validation here catches STRUCTURAL failures that
        would cause the entire transform to fail unrecoverably:
            - Missing required columns (means a source schema changed)
            - Zero rows (means a source returned no data — possible API error)
        These are fail-fast guards, not data cleaning.

    Args:
        extract_result: XCom payload from extract_data task.
        run_id:         Airflow run ID.
        max_null_threshold_pct: Max allowed null % in critical columns.
        min_rows:       Minimum rows required to continue.

    Returns:
        dict: XCom payload with validation status and validated Parquet path.

    Raises:
        ValueError: On structural validation failure (triggers Airflow retry).
    """
    import pandas as pd

    source_name = extract_result["source_name"]
    parquet_path = extract_result["parquet_path"]
    warnings: list[str] = []

    logger.info(
        "VALIDATE START | source=%s | input_rows=%d",
        source_name, extract_result["rows"],
    )
    t0 = time.perf_counter()

    df = pd.read_parquet(parquet_path)

    # ── Rule 1: Minimum row count ─────────────────────────────────────────────
    if len(df) < min_rows:
        raise ValueError(
            f"Validation FAILED | source={source_name} | "
            f"Row count {len(df)} < minimum {min_rows}. "
            f"Source may be empty or returning an error response."
        )

    # ── Rule 2: Required columns present ─────────────────────────────────────
    # These are the raw column names expected from a typical job data CSV.
    # Adjust to match your actual source schema.
    required_columns = {
        "job_title", "company_name", "location", "posted_date"
    }
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(
            f"Validation FAILED | source={source_name} | "
            f"Missing required columns: {missing}. "
            f"Source schema may have changed."
        )

    # ── Rule 3: Critical column null rate ────────────────────────────────────
    critical_cols = [c for c in ["job_title", "company_name"] if c in df.columns]
    for col in critical_cols:
        null_pct = df[col].isna().mean() * 100
        if null_pct > max_null_threshold_pct:
            raise ValueError(
                f"Validation FAILED | source={source_name} | "
                f"Column '{col}' is {null_pct:.1f}% null "
                f"(threshold: {max_null_threshold_pct}%). "
                f"Data quality issue at source."
            )
        if null_pct > 0:
            warnings.append(
                f"Column '{col}' has {null_pct:.1f}% null values. "
                f"Investigate source data quality."
            )

    # ── Rule 4: Duplicate rows check ─────────────────────────────────────────
    dup_count = df.duplicated().sum()
    if dup_count > 0:
        dup_pct = dup_count / len(df) * 100
        warnings.append(
            f"{dup_count} exact duplicate rows ({dup_pct:.1f}%) found. "
            f"These will be removed in the transform stage."
        )

    # Save validated data (same data, just confirmed clean enough to proceed)
    validated_path = _staging_path(run_id, "validated", source_name)
    df.to_parquet(validated_path, index=False, compression="snappy")

    duration = time.perf_counter() - t0
    logger.info(
        "VALIDATE COMPLETE | source=%s | rows=%d | warnings=%d | duration=%.2fs",
        source_name, len(df), len(warnings), duration,
    )
    for w in warnings:
        logger.warning("  ⚠ %s", w)

    return {
        "status": "success",
        "source_name": source_name,
        "rows": len(df),
        "duration_s": round(duration, 3),
        "parquet_path": str(validated_path),
        "warnings": warnings,
        "metadata": {
            "duplicate_rows": int(dup_count),
            "columns_validated": critical_cols,
        },
    }


# =============================================================================
# TASK 4: transform_data
# =============================================================================

def transform_data(
    validate_result: dict,
    run_id: str,
) -> dict:
    """
    Apply the full JobListing transformation pipeline to the validated DataFrame.

    Delegates to JobListingTransformer which runs 15 ordered transformation steps:
        1.  Map raw source columns → canonical schema columns
        2.  Validate schema (required columns present post-mapping)
        3.  Remove exact duplicates
        4.  Deduplicate by business key (source_job_id + source_name)
        5.  Normalise job titles (strip, title-case)
        6.  Standardise company names (strip, dedupe casing)
        7.  Normalise locations (parse city / state / country)
        8.  Clean salary values (strip currency symbols, remove non-numeric)
        9.  Annualise salary (convert hourly/monthly to annual)
        10. Validate salary bounds ($10k–$5M range)
        11. Standardise work arrangement (REMOTE/HYBRID/ON_SITE/UNSPECIFIED)
        12. Normalise experience level (map freetext → controlled vocabulary)
        13. Extract skills (regex-based keyword extraction → pipe-separated list)
        14. Validate and parse posting dates
        15. Final type casting (str→date, str→float, str→bool)

    WHY separate transform from validate?
        Airflow can retry transform independently if, say, a new regex pattern
        causes an unhandled exception on one run. Without the separate task,
        re-running would force a full re-extraction from the source API.

    Args:
        validate_result: XCom payload from validate_data task.
        run_id:          Airflow run ID.

    Returns:
        dict: XCom payload with transformed row count and Parquet path.

    Raises:
        RuntimeError: On unrecoverable transformation failure.
    """
    import pandas as pd

    from jobpulse.transformation.base import DataTransformationError
    from jobpulse.transformation.job_listing_transformer import JobListingTransformer

    source_name = validate_result["source_name"]
    parquet_path = validate_result["parquet_path"]

    logger.info(
        "TRANSFORM START | source=%s | input_rows=%d",
        source_name, validate_result["rows"],
    )
    t0 = time.perf_counter()

    df = pd.read_parquet(parquet_path)
    transformer = JobListingTransformer()

    try:
        transformed_df, report = transformer.run(df)
    except DataTransformationError as exc:
        logger.error(
            "TRANSFORM FAILED | source=%s | step=%s | error=%s",
            source_name, exc.step_name, exc,
        )
        raise RuntimeError(
            f"Transformation failed for source '{source_name}': {exc}"
        ) from exc

    # Persist transformed output to staging
    transformed_path = _staging_path(run_id, "transformed", source_name)
    transformed_df.to_parquet(transformed_path, index=False, compression="snappy")

    # ── Quality gate: reject run if drop rate is too high ────────────────────
    # If the transformer dropped >50% of rows, something is likely wrong with
    # the transformer logic or source schema — fail rather than load garbage.
    MAX_DROP_RATE_PCT = 50.0
    if report.drop_rate_pct > MAX_DROP_RATE_PCT:
        raise RuntimeError(
            f"TRANSFORM QUALITY GATE FAILED | source={source_name} | "
            f"drop_rate={report.drop_rate_pct:.1f}% > {MAX_DROP_RATE_PCT}% threshold. "
            f"Check transformer logic for schema changes."
        )

    duration = time.perf_counter() - t0
    logger.info(
        "TRANSFORM COMPLETE | source=%s | in=%d | out=%d | dropped=%d (%.1f%%) | duration=%.2fs",
        source_name,
        report.input_rows,
        report.output_rows,
        report.rows_dropped,
        report.drop_rate_pct,
        duration,
    )

    return {
        "status": "success",
        "source_name": source_name,
        "rows": report.output_rows,
        "duration_s": round(duration, 3),
        "parquet_path": str(transformed_path),
        "warnings": report.warnings,
        "metadata": {
            "input_rows": report.input_rows,
            "output_rows": report.output_rows,
            "rows_dropped": report.rows_dropped,
            "drop_rate_pct": report.drop_rate_pct,
            "step_metrics": report.step_metrics,
        },
    }


# =============================================================================
# TASK 5: load_data
# =============================================================================

def load_data(
    transform_result: dict,
    run_id: str,
    pipeline_run_id: int | None = None,
) -> dict:
    """
    Bulk-upsert the transformed DataFrame into the PostgreSQL data warehouse.

    Uses PostgresLoader which:
        - Splits the DataFrame into chunks (default 500 rows)
        - Commits each chunk atomically (chunk failure ≠ full rollback)
        - Uses INSERT ON CONFLICT DO UPDATE (UPSERT) for idempotency
        - Returns LoadingResult with inserted/updated/failed counts

    IDEMPOTENCY:
        The UPSERT key is (source_job_id, data_source_id). Running load_data
        twice for the same run produces identical database state — no duplicates,
        no errors. This makes re-running a failed DAG safe.

    Args:
        transform_result:  XCom payload from transform_data task.
        run_id:            Airflow run ID.
        pipeline_run_id:   ID of the pipeline_runs table row for this execution.

    Returns:
        dict: XCom payload with loaded row counts.

    Raises:
        RuntimeError: If load failure rate exceeds 10% (quality gate).
    """
    import pandas as pd

    from jobpulse.config.settings import get_settings
    from jobpulse.database.engine import create_db_engine, get_session_factory
    from jobpulse.loading.postgres_loader import PostgresLoader

    source_name = transform_result["source_name"]
    parquet_path = transform_result["parquet_path"]

    logger.info(
        "LOAD START | source=%s | rows=%d | run=%s",
        source_name, transform_result["rows"], run_id,
    )
    t0 = time.perf_counter()

    df = pd.read_parquet(parquet_path)

    settings = get_settings()
    engine = create_db_engine(settings)
    session_factory = get_session_factory(engine)

    loader = PostgresLoader(
        session_factory=session_factory,
        chunk_size=settings.batch_size,
        strategy="upsert",
    )

    result = loader.load(df, table_name="jobs")

    # ── Quality gate: reject load if failure rate > 10% ─────────────────────
    MAX_FAILURE_RATE_PCT = 10.0
    if result.rows_attempted > 0:
        failure_rate = result.rows_failed / result.rows_attempted * 100
        if failure_rate > MAX_FAILURE_RATE_PCT:
            raise RuntimeError(
                f"LOAD QUALITY GATE FAILED | source={source_name} | "
                f"failure_rate={failure_rate:.1f}% > {MAX_FAILURE_RATE_PCT}% threshold. "
                f"rows_failed={result.rows_failed}/{result.rows_attempted}"
            )

    duration = time.perf_counter() - t0
    logger.info(
        "LOAD COMPLETE | source=%s | inserted=%d | updated=%d | failed=%d | duration=%.2fs",
        source_name,
        result.rows_inserted,
        result.rows_updated,
        result.rows_failed,
        duration,
    )

    return {
        "status": "success" if result.rows_failed == 0 else "partial",
        "source_name": source_name,
        "rows": result.rows_loaded,
        "duration_s": round(duration, 3),
        "parquet_path": parquet_path,
        "warnings": (
            [f"{result.rows_failed} rows failed to load"]
            if result.rows_failed else []
        ),
        "metadata": {
            "rows_inserted":  result.rows_inserted,
            "rows_updated":   result.rows_updated,
            "rows_skipped":   result.rows_skipped,
            "rows_failed":    result.rows_failed,
            "chunks_loaded":  result.chunks_loaded,
            "success_rate_pct": result.success_rate_pct,
        },
    }


# =============================================================================
# TASK 6: update_pipeline_run_record
# =============================================================================

def update_pipeline_run_record(
    run_id: str,
    pipeline_run_id: int,
    load_results: list[dict],
    status: str = "SUCCESS",
) -> None:
    """
    Update the pipeline_runs table row with the final metrics for this DAG run.

    The pipeline_runs table is our operational audit log. Every DAG run creates
    a row at start (status=RUNNING) and updates it here at completion.

    WHY update at the end (not in each task)?
        Individual tasks don't know whether subsequent tasks succeeded or failed.
        Only after all tasks complete can we set status=SUCCESS vs PARTIAL.
        This task runs last (after all load tasks), so it sees the full picture.

    Args:
        run_id:         Airflow run ID.
        pipeline_run_id: The pipeline_runs.run_id PK to update.
        load_results:   List of XCom payloads from all load_data tasks.
        status:         Final pipeline status ('SUCCESS', 'PARTIAL', 'FAILED').
    """
    from sqlalchemy import text

    from jobpulse.config.settings import get_settings
    from jobpulse.database.engine import create_db_engine
    from jobpulse.database.session import db_session

    total_loaded = sum(r.get("metadata", {}).get("rows_inserted", 0) + r.get("metadata", {}).get("rows_updated", 0) for r in load_results)
    total_failed = sum(r.get("metadata", {}).get("rows_failed", 0) for r in load_results)

    logger.info(
        "Updating pipeline_runs | run_id=%d | status=%s | loaded=%d | failed=%d",
        pipeline_run_id, status, total_loaded, total_failed,
    )

    settings = get_settings()
    engine = create_db_engine(settings)

    with db_session(get_session_factory(engine)) as session:
        session.execute(
            text("""
                UPDATE public.pipeline_runs
                SET
                    status          = :status,
                    completed_at    = NOW(),
                    rows_loaded     = :rows_loaded,
                    rows_rejected   = :rows_rejected,
                    duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at))
                WHERE run_id = :run_id
            """),
            {
                "status":       status,
                "rows_loaded":  total_loaded,
                "rows_rejected": total_failed,
                "run_id":       pipeline_run_id,
            },
        )
    logger.info("pipeline_runs record updated successfully.")


# =============================================================================
# TASK 7: refresh_materialized_views
# =============================================================================

def refresh_materialized_views() -> dict:
    """
    Refresh all five JobPulse materialized views concurrently after loading.

    CONCURRENTLY means readers (Power BI) are NOT blocked during the refresh.
    Regular (non-concurrent) refresh takes an exclusive lock — Power BI would
    return errors during the 30–120 seconds the refresh takes.

    WHY CONCURRENTLY requires a UNIQUE index:
        PostgreSQL's CONCURRENTLY mode computes the new data in a temp table,
        then diffs it against the existing materialized view using the UNIQUE index
        to identify rows to add/remove. Without a UNIQUE index, PostgreSQL cannot
        do the diff and the command fails.
        All five views have UNIQUE indexes defined in analytics_views.sql.

    Execution order matters:
        mv_company_stats and mv_skill_demand must be refreshed BEFORE the
        downstream mv_salary_by_skill because Power BI may query them during
        refresh. We refresh sequentially (not in parallel) for simplicity;
        a future optimisation can use asyncio.gather() or multiprocessing.

    Returns:
        dict: Refresh result with per-view timing.

    Raises:
        RuntimeError: If any view refresh fails (triggers Airflow retry).
    """
    from sqlalchemy import text

    from jobpulse.config.settings import get_settings
    from jobpulse.database.engine import create_db_engine

    VIEWS_IN_ORDER = [
        "public.mv_company_stats",
        "public.mv_skill_demand",
        "public.mv_monthly_hiring_trend",
        "public.mv_salary_by_city",
        "public.mv_salary_by_skill",
    ]

    logger.info("Refreshing %d materialized views...", len(VIEWS_IN_ORDER))
    settings = get_settings()
    engine = create_db_engine(settings)
    timings: dict[str, float] = {}

    for view_name in VIEWS_IN_ORDER:
        t0 = time.perf_counter()
        try:
            # Autocommit is required for REFRESH MATERIALIZED VIEW CONCURRENTLY
            # DDL statements cannot run inside a transaction block.
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(
                    text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view_name}")
                )
            duration = time.perf_counter() - t0
            timings[view_name] = round(duration, 2)
            logger.info("Refreshed %s in %.2fs", view_name, duration)
        except Exception as exc:
            logger.error("Failed to refresh %s: %s", view_name, exc)
            raise RuntimeError(
                f"Materialized view refresh failed for {view_name}: {exc}"
            ) from exc

    return {
        "status": "success",
        "views_refreshed": len(VIEWS_IN_ORDER),
        "timings": timings,
    }


# =============================================================================
# TASK 8: cleanup_staging_files
# =============================================================================

def cleanup_staging_files(run_id: str, keep_days: int = 3) -> dict:
    """
    Remove staging Parquet files older than keep_days days.

    WHY keep files for N days (not delete immediately)?
        If a downstream task fails after loading completes, we may need to
        inspect the staging files for debugging. Keeping files for 3 days
        provides a debug window without letting disk usage grow unbounded.

    Args:
        run_id:     Airflow run ID (used to find this run's files).
        keep_days:  Delete staging directories older than this many days.

    Returns:
        dict: Summary of files deleted.
    """
    import shutil
    from datetime import timedelta

    cutoff = datetime.now(tz=UTC) - timedelta(days=keep_days)
    deleted = 0
    errors = 0

    for run_dir in _STAGING_DIR.iterdir():
        if not run_dir.is_dir():
            continue
        mtime = datetime.fromtimestamp(run_dir.stat().st_mtime, tz=UTC)
        if mtime < cutoff:
            try:
                shutil.rmtree(run_dir)
                deleted += 1
                logger.info("Deleted staging dir: %s", run_dir)
            except Exception as exc:
                errors += 1
                logger.warning("Failed to delete %s: %s", run_dir, exc)

    logger.info(
        "Staging cleanup complete | deleted=%d | errors=%d | cutoff=%s",
        deleted, errors, cutoff.date(),
    )
    return {
        "status": "success",
        "staging_dirs_deleted": deleted,
        "errors": errors,
    }
