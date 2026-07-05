-- Analytics Query: 06_remote_jobs_count.sql
SELECT COUNT(*) FROM fact_jobs f JOIN dim_location l ON f.sk_location_id = l.sk_location_id WHERE l.is_remote = TRUE;
