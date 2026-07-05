-- Analytics Query: 32_first_job_posted_date.sql
SELECT c.company_name, FIRST_VALUE(d.full_date) OVER(PARTITION BY c.sk_company_id ORDER BY d.full_date) as first_post FROM fact_jobs f JOIN dim_company c ON f.sk_company_id = c.sk_company_id JOIN dim_date d ON f.sk_posted_date_id = d.sk_date_id;
