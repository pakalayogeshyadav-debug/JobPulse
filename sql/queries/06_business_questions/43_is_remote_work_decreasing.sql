-- Analytics Query: 43_is_remote_work_decreasing.sql
SELECT d.year_number, d.month_number, SUM(CASE WHEN l.is_remote THEN 1 ELSE 0 END)*100.0/COUNT(*) as remote_pct FROM fact_jobs f JOIN dim_location l ON f.sk_location_id = l.sk_location_id JOIN dim_date d ON f.sk_posted_date_id = d.sk_date_id GROUP BY d.year_number, d.month_number ORDER BY d.year_number, d.month_number;
