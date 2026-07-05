-- Analytics Query: 11_avg_salary_by_role.sql
SELECT job_title, AVG(salary_min) as min_avg, AVG(salary_max) as max_avg FROM fact_jobs GROUP BY job_title;
