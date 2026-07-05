-- Analytics Query: 15_highest_salaries.sql
SELECT job_title, salary_max FROM fact_jobs WHERE salary_max IS NOT NULL ORDER BY salary_max DESC LIMIT 10;
