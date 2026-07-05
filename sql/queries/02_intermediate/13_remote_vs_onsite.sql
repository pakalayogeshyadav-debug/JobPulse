-- Analytics Query: 13_remote_vs_onsite.sql
SELECT l.is_remote, COUNT(*) FROM fact_jobs f JOIN dim_location l ON f.sk_location_id = l.sk_location_id GROUP BY l.is_remote;
