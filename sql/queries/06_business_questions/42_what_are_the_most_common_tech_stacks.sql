-- Analytics Query: 42_what_are_the_most_common_tech_stacks.sql
SELECT s.skill_name, COUNT(*) FROM bridge_job_skill b JOIN dim_skill s ON b.sk_skill_id = s.sk_skill_id GROUP BY s.skill_name ORDER BY COUNT(*) DESC;
