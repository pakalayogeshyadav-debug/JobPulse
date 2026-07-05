-- Analytics Query: 19_jobs_above_market_avg.sql
SELECT f.job_title, c.company_name, f.salary_min FROM fact_jobs f JOIN dim_company c ON f.sk_company_id = c.sk_company_id WHERE f.salary_min > (SELECT AVG(salary_min) FROM fact_jobs);
