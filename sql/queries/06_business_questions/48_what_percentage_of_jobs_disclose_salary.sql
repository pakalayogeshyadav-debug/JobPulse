-- Analytics Query: 48_what_percentage_of_jobs_disclose_salary.sql
SELECT SUM(CASE WHEN salary_min IS NOT NULL THEN 1 ELSE 0 END)*100.0/COUNT(*) as pct_disclosed FROM fact_jobs;
