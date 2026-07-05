-- Analytics Query: 08_jobs_with_salary.sql
SELECT COUNT(*) FROM fact_jobs WHERE salary_min IS NOT NULL;
