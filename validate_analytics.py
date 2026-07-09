import os
import sys
from pathlib import Path
import logging

_PROJECT_ROOT = Path(__file__).resolve().parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from frontend.services.analytics_service import (
    get_home_kpis,
    get_live_jobs,
    get_top_skills,
    get_company_hiring,
    get_salary_by_role,
    get_pipeline_health,
    get_jobs_over_time,
    get_work_arrangement_breakdown
)

def main():
    logging.basicConfig(level=logging.INFO)
    print("--- Testing Analytics Queries against 3NF Database ---")
    
    print("\n--- get_home_kpis ---")
    try:
        kpis = get_home_kpis()
        print(f"KPIs: {kpis}")
    except Exception as e:
        print(f"Error in get_home_kpis: {e}")
        
    print("\n--- get_live_jobs ---")
    try:
        df = get_live_jobs(5)
        print(f"Rows: {len(df)}")
        if not df.empty:
            print(df.head(2))
    except Exception as e:
        print(f"Error in get_live_jobs: {e}")
        
    print("\n--- get_top_skills ---")
    try:
        df = get_top_skills(5)
        print(f"Rows: {len(df)}")
        if not df.empty:
            print(df.head(2))
    except Exception as e:
        print(f"Error in get_top_skills: {e}")
        
    print("\n--- get_company_hiring ---")
    try:
        df = get_company_hiring(5)
        print(f"Rows: {len(df)}")
        if not df.empty:
            print(df.head(2))
    except Exception as e:
        print(f"Error in get_company_hiring: {e}")
        
    print("\n--- get_salary_by_role ---")
    try:
        df = get_salary_by_role(5)
        print(f"Rows: {len(df)}")
        if not df.empty:
            print(df.head(2))
    except Exception as e:
        print(f"Error in get_salary_by_role: {e}")
        
    print("\n--- get_pipeline_health ---")
    try:
        df = get_pipeline_health()
        print(f"Rows: {len(df)}")
        if not df.empty:
            print(df.head(2))
    except Exception as e:
        print(f"Error in get_pipeline_health: {e}")
        
    print("\n--- get_jobs_over_time ---")
    try:
        df = get_jobs_over_time()
        print(f"Rows: {len(df)}")
        if not df.empty:
            print(df.head(2))
    except Exception as e:
        print(f"Error in get_jobs_over_time: {e}")
        
    print("\n--- get_work_arrangement_breakdown ---")
    try:
        df = get_work_arrangement_breakdown()
        print(f"Rows: {len(df)}")
        if not df.empty:
            print(df.head(2))
    except Exception as e:
        print(f"Error in get_work_arrangement_breakdown: {e}")

if __name__ == '__main__':
    main()
