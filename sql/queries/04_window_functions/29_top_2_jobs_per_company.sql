-- Analytics Query: 29_top_2_jobs_per_company.sql
SELECT * FROM (SELECT f.job_title, c.company_name, ROW_NUMBER() OVER(PARTITION BY c.company_name ORDER BY f.salary_max DESC) as rnk FROM fact_jobs f JOIN dim_company c ON f.sk_company_id = c.sk_company_id) t WHERE rnk <= 2;
