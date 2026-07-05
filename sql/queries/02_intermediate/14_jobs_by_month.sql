-- Analytics Query: 14_jobs_by_month.sql
SELECT d.year_number, d.month_name, COUNT(*) FROM fact_jobs f JOIN dim_date d ON f.sk_posted_date_id = d.sk_date_id GROUP BY d.year_number, d.month_name ORDER BY d.year_number, d.month_name;
