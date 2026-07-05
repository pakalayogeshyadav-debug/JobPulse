-- Analytics Query: 25_salary_percentiles.sql
SELECT job_title, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary_min) as median_salary FROM fact_jobs GROUP BY job_title;
