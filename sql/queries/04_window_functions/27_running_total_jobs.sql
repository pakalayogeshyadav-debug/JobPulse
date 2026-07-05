-- Analytics Query: 27_running_total_jobs.sql
SELECT d.full_date, COUNT(*) as daily_jobs, SUM(COUNT(*)) OVER (ORDER BY d.full_date) as running_total FROM fact_jobs f JOIN dim_date d ON f.sk_posted_date_id = d.sk_date_id GROUP BY d.full_date;
