-- Analytics Query: 12_top_10_skills.sql
SELECT s.skill_name, COUNT(*) as freq FROM bridge_job_skill b JOIN dim_skill s ON b.sk_skill_id = s.sk_skill_id GROUP BY s.skill_name ORDER BY freq DESC LIMIT 10;
