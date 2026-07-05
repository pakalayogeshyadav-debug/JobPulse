-- Analytics Query: 28_salary_vs_company_avg.sql
SELECT f.job_id, f.job_title, f.salary_min, AVG(f.salary_min) OVER (PARTITION BY f.sk_company_id) as company_avg FROM fact_jobs f;
