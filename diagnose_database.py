import os

import psycopg2
from dotenv import load_dotenv
from sqlalchemy import text


def run_diagnostics():
    load_dotenv()
    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "jobpulse")
    db_user = os.environ.get("DB_USER", "postgres")
    db_pass = os.environ.get("DB_PASSWORD", "Yogi@123")
    
    print("========================================")
    print("Database Diagnostic Tool")
    print("========================================\n")
    
    failures = 0

    # 1. Check psycopg2 native connection
    print("1. Testing Native PostgreSQL Reachability & Auth...")
    try:
        conn = psycopg2.connect(
            dbname=db_name, user=db_user, password=db_pass, host=db_host, port=db_port
        )
        print("   ✅ PASS: Connected to PostgreSQL.")
        conn.close()
    except Exception as e:
        print(f"   ❌ FAIL: Could not connect natively. {e}")
        failures += 1

    # 2. Check SQLAlchemy Engine
    print("2. Testing SQLAlchemy Engine Connection...")
    try:
        from src.jobpulse.config.settings import get_settings
        from src.jobpulse.database.engine import create_db_engine
        engine = create_db_engine(get_settings())
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("   ✅ PASS: SQLAlchemy connection successful.")
    except Exception as e:
        print(f"   ❌ FAIL: SQLAlchemy connection failed. {e}")
        failures += 1
        
    # 3. Check Database and Tables
    print("3. Validating Core Tables...")
    try:
        with engine.connect() as conn:
            tables = ["fact_jobs", "dim_company", "dim_skill", "dim_location"]
            for table in tables:
                res = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()
                if res is not None:
                    print(f"   ✅ PASS: Table '{table}' exists. Row count: {res[0]}")
                else:
                    print(f"   ❌ FAIL: Table '{table}' could not be counted.")
                    failures += 1
    except Exception as e:
        print(f"   ❌ FAIL: Error validating tables. {e}")
        failures += 1

    print("\n========================================")
    if failures == 0:
        print("DIAGNOSTICS PASSED: ✅ Database is fully operational.")
    else:
        print(f"DIAGNOSTICS FAILED: ❌ {failures} issues detected.")
    print("========================================")

if __name__ == "__main__":
    run_diagnostics()
