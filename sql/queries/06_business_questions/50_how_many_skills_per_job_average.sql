-- Analytics Query: 50_how_many_skills_per_job_average.sql
WITH SkillCounts AS (SELECT sk_fact_job_id, COUNT(*) as scnt FROM bridge_job_skill GROUP BY sk_fact_job_id) SELECT AVG(scnt) FROM SkillCounts;
