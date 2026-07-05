-- Analytics Query: 09_jobs_by_company.sql
SELECT c.company_name, COUNT(*) as jobs FROM fact_jobs f JOIN dim_company c ON f.sk_company_id = c.sk_company_id GROUP BY c.company_name ORDER BY jobs DESC;
