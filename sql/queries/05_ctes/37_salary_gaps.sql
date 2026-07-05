-- Analytics Query: 37_salary_gaps.sql
WITH RoleAverages AS (SELECT job_title, AVG(salary_min) as avg_min FROM fact_jobs GROUP BY job_title) SELECT f.job_title, f.salary_min, r.avg_min, f.salary_min - r.avg_min as gap FROM fact_jobs f JOIN RoleAverages r ON f.job_title = r.job_title;
