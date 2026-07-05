-- Analytics Query: 24_job_title_clustering.sql
SELECT SUBSTRING(job_title FROM 1 FOR 10) as title_prefix, COUNT(*) FROM fact_jobs GROUP BY title_prefix ORDER BY COUNT(*) DESC LIMIT 10;
