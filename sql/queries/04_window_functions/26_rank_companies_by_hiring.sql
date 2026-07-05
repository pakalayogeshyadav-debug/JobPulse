-- Analytics Query: 26_rank_companies_by_hiring.sql
SELECT company_name, RANK() OVER(ORDER BY COUNT(*) DESC) as hiring_rank FROM fact_jobs f JOIN dim_company c ON f.sk_company_id = c.sk_company_id GROUP BY company_name;
