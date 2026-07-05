-- Analytics Query: 23_missing_salary_ratio.sql
SELECT c.company_name, SUM(CASE WHEN f.salary_min IS NULL THEN 1 ELSE 0 END)*100.0/COUNT(*) as no_salary_pct FROM fact_jobs f JOIN dim_company c ON f.sk_company_id = c.sk_company_id GROUP BY c.company_name ORDER BY no_salary_pct DESC;
