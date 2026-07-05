from sqlalchemy import text
from src.jobpulse.config.settings import get_settings
from src.jobpulse.database.engine import create_db_engine


def run_validation():
    settings = get_settings()
    engine = create_db_engine(settings)
    queries = [
        "SELECT COUNT(*) FROM fact_jobs;",
        "SELECT COUNT(*) FROM jobs;",
        "SELECT COUNT(*) FROM dim_company;",
        "SELECT COUNT(*) FROM dim_skill;",
        "SELECT NOW();"
    ]
    
    with engine.connect() as conn:
        for q in queries:
            try:
                res = conn.execute(text(q)).fetchone()
                print(f"{q} -> {res[0]}")
            except Exception as e:
                print(f"{q} -> FAILED: {e}")
                
if __name__ == "__main__":
    run_validation()
