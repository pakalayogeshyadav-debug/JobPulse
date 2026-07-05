# ETL Pipeline

The JobPulse ETL (Extract, Transform, Load) pipeline is built in Python and orchestrated by Apache Airflow.

## Incremental Processing Logic

To optimize performance and minimize database I/O, the pipeline runs incrementally:

1. **Watermark Read**: For a given `source_name`, fetch the `last_successful_run_at` from `etl_watermarks`.
2. **Data Extraction**: Pull data from the source.
3. **Time Filtering**: Drop records older than `watermark - late_arrival_buffer` (default 24h). This ensures late-arriving data is captured.
4. **Change Detection**: 
   - Compute a SHA-256 hash for canonical columns (`title`, `company`, `salary`, `description`, etc.).
   - Bulk-lookup known hashes from `job_content_hashes`.
   - Classify rows as `NEW`, `UPDATED`, or `UNCHANGED`.
5. **Load**: 
   - UPSERT only `NEW` and `UPDATED` rows using `INSERT ... ON CONFLICT DO UPDATE`.
   - Skip `UNCHANGED` rows entirely.
6. **Watermark Advance**: Update `etl_watermarks` and `job_content_hashes` only if the load succeeds.

## Layers

### 1. Extraction Layer (`src/jobpulse/extraction/`)
Defines a `BaseExtractor` abstract class.
- **`CsvExtractor`**: Handles local and chunked CSV ingestion (e.g. Kaggle datasets).
- **`ApiExtractor`**: Pluggable interface for REST APIs with pagination and rate-limit handling.

### 2. Validation Layer (`src/jobpulse/validation/`)
Pre-transform quality checks. Prevents schema drift and catastrophic pipeline failure if source data structures unexpectedly change.

### 3. Transformation Layer (`src/jobpulse/transformation/`)
- Type casting (dates, numerics).
- Text standardisation (lowercasing, stripping whitespace).
- Salary normalization (annualizing hourly rates, standardizing currencies).
- Entity extraction (parsing "City, State" into distinct columns).

### 4. Loading Layer (`src/jobpulse/incremental/loader.py`)
- Executes bulk UPSERTs via SQLAlchemy Core for maximum performance.
- Handles intra-batch duplicate removal to prevent PostgreSQL unique constraint violations during `ON CONFLICT` execution.

## Orchestration (Airflow)
Defined in `dags/jobpulse_etl_dag.py`.
- Scheduled dynamically (e.g., daily at 03:00 UTC).
- Tasks communicate via Parquet files stored in a staging directory, avoiding XCom size limits.
- Configured with robust retries and exponential backoff for network boundaries (Extraction).
