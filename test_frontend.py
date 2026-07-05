import importlib
import traceback

pages = [
    "frontend.pages.dashboard",
    "frontend.pages.live_jobs",
    "frontend.pages.pipeline",
    "frontend.pages.companies",
    "frontend.pages.skills",
    "frontend.pages.salary",
    "frontend.pages.validation",
    "frontend.pages.warehouse",
    "frontend.pages.db_explorer",
    "frontend.pages.logs",
    "frontend.pages.sql_playground",
    "frontend.pages.airflow",
    "frontend.pages.about",
]

for page in pages:
    try:
        importlib.import_module(page)
    except Exception:
        print(f"Error in {page}:")
        traceback.print_exc()
        print("-" * 40)
