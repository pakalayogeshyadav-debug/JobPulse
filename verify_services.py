"""
Quick import and query verification — runs outside Streamlit to confirm all
frontend services can connect and return data.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

# Simulate what Streamlit does when app.py is loaded
import os
os.environ.setdefault("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "false")

print("=" * 60)
print("FRONTEND SERVICE VERIFICATION")
print("=" * 60)

# Test 1: database_service
print("\n[1] Testing database_service.check_connection()...")
from frontend.services.database_service import check_connection, fetch_data
health = check_connection()
print(f"    connected: {health['connected']}")
print(f"    status: {health['status']}")
if health['connected']:
    print(f"    latency_ms: {health['latency_ms']}")
    print(f"    db_name: {health['db_name']}")
else:
    print(f"    error: {health.get('error')}")

# Test 2: fetch_data
print("\n[2] Testing fetch_data()...")
df = fetch_data("SELECT COUNT(*) AS job_count FROM jobs")
if not df.empty:
    print(f"    job_count: {df.iloc[0]['job_count']}")
else:
    print("    ERROR: returned empty DataFrame")

# Test 3: analytics_service
print("\n[3] Testing analytics_service.get_home_kpis()...")
from frontend.services.analytics_service import get_home_kpis
kpis = get_home_kpis()
for k, v in kpis.items():
    print(f"    {k}: {v}")

print("\n[4] Testing analytics_service.get_top_skills()...")
from frontend.services.analytics_service import get_top_skills
skills = get_top_skills(5)
print(f"    rows returned: {len(skills)}")
if not skills.empty:
    print(f"    top skill: {skills.iloc[0]['skill_name']} ({skills.iloc[0]['job_count']} jobs)")

print("\n[5] Testing analytics_service.get_pipeline_health()...")
from frontend.services.analytics_service import get_pipeline_health
pipe = get_pipeline_health()
print(f"    rows returned: {len(pipe)}")
if not pipe.empty:
    print(pipe[["source_name","total_runs","success_runs","success_rate_pct"]].to_string(index=False))

print("\n[6] Testing validation_service.get_validation_summary()...")
from frontend.services.validation_service import get_validation_summary
val = get_validation_summary()
for k, v in val.items():
    print(f"    {k}: {v}")

print("\n[7] Testing validation_service.get_validation_history()...")
from frontend.services.validation_service import get_validation_history
hist = get_validation_history()
print(f"    rows returned: {len(hist)}")
if not hist.empty:
    print(f"    columns: {list(hist.columns)}")

print("\n[8] Testing warehouse_service.get_tables_metadata()...")
from frontend.services.warehouse_service import get_tables_metadata
tables = get_tables_metadata()
print(f"    tables found: {len(tables)}")
if not tables.empty:
    print(f"    table names: {tables['table_name'].tolist()}")

print("\n" + "=" * 60)
print("VERIFICATION COMPLETE")
print("=" * 60)
