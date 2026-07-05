-- Analytics Query: 47_which_month_has_most_postings.sql
SELECT d.month_name, COUNT(*) as postings FROM fact_jobs f JOIN dim_date d ON f.sk_posted_date_id = d.sk_date_id GROUP BY d.month_name ORDER BY postings DESC;
