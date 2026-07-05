-- Analytics Query: 44_which_companies_hire_the_most_juniors.sql
SELECT c.company_name, COUNT(*) FROM fact_jobs f JOIN dim_company c ON f.sk_company_id = c.sk_company_id WHERE f.job_title ILIKE %Junior% OR f.job_title ILIKE %Entry% GROUP BY c.company_name ORDER BY COUNT(*) DESC;
