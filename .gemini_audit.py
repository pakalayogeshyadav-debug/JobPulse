"""Audit script: check database state before refactoring."""
from jobpulse.config.settings import get_settings
from jobpulse.database.engine import create_db_engine
from sqlalchemy import text

settings = get_settings()
engine = create_db_engine(settings)

with engine.connect() as conn:
    # Check data_sources
    r = conn.execute(text("SELECT data_source_id, source_name FROM data_sources ORDER BY data_source_id"))
    print("=== data_sources ===")
    for row in r:
        print(row)

    # Check sequences
    r = conn.execute(text("SELECT pg_get_serial_sequence('data_sources','data_source_id') AS seq"))
    seq = r.scalar()
    print(f"data_sources sequence: {seq}")
    if seq:
        r = conn.execute(text(f"SELECT last_value, is_called FROM {seq}"))
        print(f"  last_value, is_called: {r.fetchone()}")
    r = conn.execute(text("SELECT MAX(data_source_id) FROM data_sources"))
    print(f"  MAX(data_source_id): {r.scalar()}")

    # pipeline_runs sequence
    r = conn.execute(text("SELECT pg_get_serial_sequence('pipeline_runs','run_id') AS seq"))
    seq2 = r.scalar()
    print(f"pipeline_runs sequence: {seq2}")
    if seq2:
        r = conn.execute(text(f"SELECT last_value, is_called FROM {seq2}"))
        print(f"  last_value, is_called: {r.fetchone()}")

    # Check pipeline_runs count
    r = conn.execute(text("SELECT COUNT(*) FROM pipeline_runs"))
    print(f"pipeline_runs count: {r.scalar()}")

    # Check FK on pipeline_runs
    r = conn.execute(text(
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid = 'pipeline_runs'::regclass AND contype = 'f'"
    ))
    fks = [row[0] for row in r]
    print(f"pipeline_runs FK constraints: {fks}")

    # Check jobs count
    r = conn.execute(text("SELECT COUNT(*) FROM jobs"))
    print(f"jobs count: {r.scalar()}")

    # Check if pipeline_runs.data_source_id has FK
    r = conn.execute(text(
        "SELECT tc.constraint_name, tc.table_name, "
        "kcu.column_name, ccu.table_name AS foreign_table_name "
        "FROM information_schema.table_constraints AS tc "
        "JOIN information_schema.key_column_usage AS kcu "
        "  ON tc.constraint_name = kcu.constraint_name "
        "JOIN information_schema.constraint_column_usage AS ccu "
        "  ON ccu.constraint_name = tc.constraint_name "
        "WHERE tc.constraint_type = 'FOREIGN KEY' "
        "  AND tc.table_name = 'pipeline_runs'"
    ))
    print("pipeline_runs foreign keys:")
    for row in r:
        print(f"  {row}")
