-- Analytics Query: 17_salary_spread_by_company.sql
SELECT c.company_name, MAX(salary_max) - MIN(salary_min) as spread FROM fact_jobs f JOIN dim_company c ON f.sk_company_id = c.sk_company_id GROUP BY c.company_name HAVING MAX(salary_max) - MIN(salary_min) > 0 ORDER BY spread DESC;
