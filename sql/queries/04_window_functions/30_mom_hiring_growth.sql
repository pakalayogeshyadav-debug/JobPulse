-- Analytics Query: 30_mom_hiring_growth.sql
SELECT d.month_number, COUNT(*) as curr_month, LAG(COUNT(*)) OVER(ORDER BY d.month_number) as prev_month FROM fact_jobs f JOIN dim_date d ON f.sk_posted_date_id = d.sk_date_id GROUP BY d.month_number;
