-- Analytics Query: 41_which_city_pays_highest_for_de.sql
SELECT l.city, AVG(f.salary_max) as avg_max FROM fact_jobs f JOIN dim_location l ON f.sk_location_id = l.sk_location_id WHERE f.job_title ILIKE %Data Engineer% GROUP BY l.city ORDER BY avg_max DESC;
