import os

import psycopg2
import pytest
from dotenv import load_dotenv

# Load env safely
load_dotenv()

@pytest.fixture(scope="module")
def db_connection():
    """Fixture to provide a raw psycopg2 database connection for auditing."""
    try:
        conn = psycopg2.connect(
            dbname=os.environ.get("DB_NAME", "jobpulse"),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", "Yogi@123"),
            host=os.environ.get("DB_HOST", "localhost"),
            port=os.environ.get("DB_PORT", "5432")
        )
        yield conn
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def test_operational_tables_exist(db_connection):
    """Verify that operational ETL tables exist."""
    cur = db_connection.cursor()
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public';")
    tables = [r[0] for r in cur.fetchall()]
    
    expected_tables = ["data_sources", "pipeline_runs", "jobs"]
    for t in expected_tables:
        assert t in tables, f"Missing operational table: {t}"

def test_warehouse_tables_exist(db_connection):
    """Verify that the Kimball Star Schema tables exist."""
    cur = db_connection.cursor()
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public';")
    tables = [r[0] for r in cur.fetchall()]
    
    expected_tables = [
        "dim_date", "dim_company", "dim_location", "dim_skill",
        "fact_jobs", "bridge_job_skill"
    ]
    for t in expected_tables:
        assert t in tables, f"Missing warehouse table: {t}"

def test_analytical_views_exist(db_connection):
    """Verify that PowerBI-ready analytical views exist."""
    cur = db_connection.cursor()
    cur.execute("SELECT viewname FROM pg_views WHERE schemaname = 'public';")
    views = [r[0] for r in cur.fetchall()]
    
    expected_views = [
        "vw_salary_by_role", "vw_top_skills", "vw_remote_jobs",
        "vw_jobs_by_location", "vw_company_hiring", "vw_pipeline_health"
    ]
    for v in expected_views:
        assert v in views, f"Missing analytical view: {v}"

def test_foreign_keys_exist(db_connection):
    """Audit the database to ensure all expected foreign key constraints exist."""
    cur = db_connection.cursor()
    cur.execute("""
        SELECT conname, relname 
        FROM pg_constraint c 
        JOIN pg_namespace n ON n.oid = c.connamespace 
        JOIN pg_class t ON t.oid = c.conrelid 
        WHERE n.nspname = 'public' AND contype = 'f';
    """)
    constraints = [(r[0], r[1]) for r in cur.fetchall()]
    
    # Expected constraint names mapped to their tables
    expected_fks = [
        ("jobs_pipeline_run_id_fkey", "jobs"),
        ("jobs_data_source_id_fkey", "jobs"),
        ("fk_pipeline_runs_data_source", "pipeline_runs"), # The one we just added
        ("fk_fact_pipeline_run", "fact_jobs"),
        ("fk_fact_data_source", "fact_jobs"),
        ("fk_fact_date", "fact_jobs"),
        ("fk_fact_location", "fact_jobs"),
        ("fk_fact_company", "fact_jobs"),
        ("fk_bridge_skill", "bridge_job_skill"),
        ("fk_bridge_job", "bridge_job_skill"),
    ]
    for fk, table in expected_fks:
        assert (fk, table) in constraints, f"Missing FK constraint {fk} on {table}"

def test_indexes_exist(db_connection):
    """Audit the database to ensure all expected indexes exist for performance."""
    cur = db_connection.cursor()
    cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public';")
    indexes = [r[0] for r in cur.fetchall()]
    
    expected_indexes = [
        # Operational Indexes
        "ix_jobs_is_active", "ix_jobs_pipeline_run_id", "ix_jobs_posted_date", "ix_jobs_data_source_id",
        "ix_pipeline_runs_data_source_id",
        
        # Warehouse Indexes
        "idx_fact_jobs_company_id", "idx_fact_jobs_location_id", "idx_fact_jobs_date_id",
        "idx_fact_jobs_data_source_id", "idx_fact_jobs_pipeline_run_id",
        "idx_bridge_skill_id", "idx_fact_jobs_title_salary", "idx_dim_date_ymd",
        "idx_dim_location_remote", "idx_fact_jobs_active"
    ]
    for idx in expected_indexes:
        assert idx in indexes, f"Missing index: {idx}"
