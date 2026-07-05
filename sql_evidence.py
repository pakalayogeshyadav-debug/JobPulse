
from sqlalchemy import create_engine, text

from jobpulse.config.settings import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")

queries = [
    "SELECT COUNT(*) FROM jobs;",
    "SELECT COUNT(*) FROM pipeline_runs;",
    "SELECT COUNT(*) FROM fact_jobs;",
    "SELECT COUNT(*) FROM dim_company;",
    "SELECT COUNT(*) FROM dim_skill;",
]

with open("evidence_sql.txt", "w", encoding="utf-8") as f:
    f.write("=========================================\n")
    f.write("10. SQL Output for Counts\n")
    with engine.connect() as conn:
        for q in queries:
            try:
                res = conn.execute(text(q)).scalar()
                f.write(f"{q}\n-> {res}\n\n")
            except Exception as e:
                f.write(f"{q}\n-> ERROR: {e}\n\n")

        f.write("=========================================\n")
        f.write("11. Stored Procedures\n")
        try:
            conn.execute(text("CALL refresh_dimensions();"))
            f.write("CALL refresh_dimensions();\n-> SUCCESS\n\n")
            conn.execute(text("CALL refresh_fact_jobs();"))
            f.write("CALL refresh_fact_jobs();\n-> SUCCESS\n\n")
        except Exception as e:
            f.write(f"Stored Procedure ERROR: {e}\n\n")

        f.write("=========================================\n")
        f.write("12. Analytical Views\n")
        views = [
            "SELECT * FROM vw_salary_by_role LIMIT 5;",
            "SELECT * FROM vw_top_skills LIMIT 5;"
        ]
        for v in views:
            try:
                res = conn.execute(text(v)).fetchall()
                f.write(f"{v}\n")
                for row in res:
                    f.write(f"  {row}\n")
                f.write("\n")
            except Exception as e:
                f.write(f"{v}\n-> ERROR: {e}\n\n")
                
        f.write("=========================================\n")
        f.write("13. Power BI Source Queries\n")
        pbi_queries = [
            "SELECT * FROM vw_salary_by_role LIMIT 1;",
            "SELECT * FROM vw_remote_jobs LIMIT 1;",
            "SELECT * FROM vw_company_hiring LIMIT 1;"
        ]
        for q in pbi_queries:
            try:
                res = conn.execute(text(q)).fetchall()
                f.write(f"{q}\n-> SUCCESS (Returned {len(res)} rows)\n\n")
            except Exception as e:
                f.write(f"{q}\n-> ERROR: {e}\n\n")
