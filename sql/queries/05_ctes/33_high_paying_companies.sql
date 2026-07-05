-- Analytics Query: 33_high_paying_companies.sql
WITH AvgSal AS (SELECT AVG(salary_max) as market_avg FROM fact_jobs) SELECT c.company_name, AVG(f.salary_max) FROM fact_jobs f JOIN dim_company c ON f.sk_company_id = c.sk_company_id CROSS JOIN AvgSal WHERE f.salary_max > AvgSal.market_avg GROUP BY c.company_name;
