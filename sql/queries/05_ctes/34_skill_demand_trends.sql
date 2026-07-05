-- Analytics Query: 34_skill_demand_trends.sql
WITH SkillCounts AS (SELECT s.skill_name, d.month_number, COUNT(*) as cnt FROM bridge_job_skill b JOIN dim_skill s ON b.sk_skill_id = s.sk_skill_id JOIN fact_jobs f ON b.sk_fact_job_id = f.sk_fact_job_id JOIN dim_date d ON f.sk_posted_date_id = d.sk_date_id GROUP BY s.skill_name, d.month_number) SELECT * FROM SkillCounts;
