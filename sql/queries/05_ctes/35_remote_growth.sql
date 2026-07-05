-- Analytics Query: 35_remote_growth.sql
WITH RemoteStats AS (SELECT d.year_number, COUNT(*) as remote_jobs FROM fact_jobs f JOIN dim_location l ON f.sk_location_id = l.sk_location_id JOIN dim_date d ON f.sk_posted_date_id = d.sk_date_id WHERE l.is_remote = TRUE GROUP BY d.year_number) SELECT * FROM RemoteStats;
