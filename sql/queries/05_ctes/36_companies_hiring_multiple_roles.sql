-- Analytics Query: 36_companies_hiring_multiple_roles.sql
WITH CompanyRoles AS (SELECT sk_company_id, COUNT(DISTINCT job_title) as roles FROM fact_jobs GROUP BY sk_company_id) SELECT c.company_name FROM CompanyRoles cr JOIN dim_company c ON cr.sk_company_id = c.sk_company_id WHERE cr.roles > 5;
