"""jobpulse.loading — Data loading sub-package.

Responsible for the LOAD step of the ETL pipeline.
Writes validated, transformed DataFrames into the PostgreSQL data warehouse.

Loading Strategies:
    1. Bulk Insert      — Fast insert for initial data loads (no conflict handling)
    2. Upsert           — INSERT ... ON CONFLICT DO UPDATE for incremental loads
    3. Truncate + Load  — Full table replacement (slow changing dimensions)
    4. Append Only      — Append-only for audit/log tables

Design Principles:
    - Loaders are idempotent: safe to re-run without duplicating data
    - Use bulk operations (SQLAlchemy bulk_insert_mappings) not row-by-row inserts
    - Loading is transactional: all-or-nothing per batch
    - Loaders receive validated DataFrames — no transformation happens here

Loader Hierarchy:
    BaseLoader (abstract)
        └── PostgresLoader   ← Loads into PostgreSQL via SQLAlchemy

Usage:
    from jobpulse.loading.postgres_loader import PostgresLoader
    loader = PostgresLoader(session_factory=SessionFactory)
    loader.load(df, table_name="job_listings")
"""
