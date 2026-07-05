-- Analytics Query: 31_salary_deciles.sql
SELECT job_title, salary_min, NTILE(10) OVER(ORDER BY salary_min) as decile FROM fact_jobs WHERE salary_min IS NOT NULL;
