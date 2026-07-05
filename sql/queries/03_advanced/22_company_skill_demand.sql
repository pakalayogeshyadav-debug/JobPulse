-- Analytics Query: 22_company_skill_demand.sql
SELECT c.company_name, s.skill_name, COUNT(*) as demand FROM fact_jobs f JOIN dim_company c ON f.sk_company_id = c.sk_company_id JOIN bridge_job_skill b ON f.sk_fact_job_id = b.sk_fact_job_id JOIN dim_skill s ON b.sk_skill_id = s.sk_skill_id GROUP BY c.company_name, s.skill_name ORDER BY demand DESC LIMIT 50;
