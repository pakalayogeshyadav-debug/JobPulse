import pandas as pd
from src.jobpulse.config.settings import Settings
from src.jobpulse.database.engine import create_db_engine

engine = create_db_engine(Settings())

print("\n--- Test 4: Verify SQL Playground ---")
for table in ['jobs', 'pipeline_runs', 'bridge_job_skill']:
    try:
        count = pd.read_sql(f"SELECT COUNT(*) as c FROM {table};", engine).iloc[0]['c']
        print(f"SELECT COUNT(*) FROM {table}; -> {count}")
    except Exception as e:
        print(f"{table} ERROR: {e}")

print("\n--- Test 5: Verify PostgreSQL ---")
queries = [
    "SELECT current_user;",
    "SELECT current_database();",
    "SELECT version();"
]
for q in queries:
    try:
        res = pd.read_sql(q, engine).iloc[0, 0]
        print(f"{q} -> {res}")
    except Exception as e:
        print(f"{q} ERROR: {e}")
