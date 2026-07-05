-- Analytics Query: 10_jobs_by_location.sql
SELECT l.city, l.state, COUNT(*) as jobs FROM fact_jobs f JOIN dim_location l ON f.sk_location_id = l.sk_location_id GROUP BY l.city, l.state ORDER BY jobs DESC;
