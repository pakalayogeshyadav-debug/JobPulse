-- Analytics Query: 21_remote_salary_premium.sql
SELECT l.is_remote, AVG((f.salary_min + f.salary_max)/2) as avg_salary FROM fact_jobs f JOIN dim_location l ON f.sk_location_id = l.sk_location_id GROUP BY l.is_remote;
