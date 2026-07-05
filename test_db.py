from frontend.services.analytics_service import get_home_kpis, get_live_jobs

try:
    print("Fetching KPIs...")
    kpis = get_home_kpis()
    print("KPIs:", kpis)
except Exception as e:
    print("KPIs Error:", e)

try:
    print("Fetching Live Jobs...")
    jobs = get_live_jobs(10)
    print("Live Jobs:", len(jobs))
except Exception as e:
    print("Live Jobs Error:", e)
