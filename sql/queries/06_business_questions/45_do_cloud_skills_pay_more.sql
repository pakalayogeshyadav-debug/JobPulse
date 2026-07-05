-- Analytics Query: 45_do_cloud_skills_pay_more.sql
SELECT s.skill_category, AVG(f.salary_max) FROM bridge_job_skill b JOIN dim_skill s ON b.sk_skill_id = s.sk_skill_id JOIN fact_jobs f ON b.sk_fact_job_id = f.sk_fact_job_id GROUP BY s.skill_category ORDER BY AVG(f.salary_max) DESC;
