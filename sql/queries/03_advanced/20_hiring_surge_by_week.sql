-- Analytics Query: 20_hiring_surge_by_week.sql
SELECT d.week_of_year, COUNT(*) as volume FROM fact_jobs f JOIN dim_date d ON f.sk_posted_date_id = d.sk_date_id GROUP BY d.week_of_year ORDER BY volume DESC;
