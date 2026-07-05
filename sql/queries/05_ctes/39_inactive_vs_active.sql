-- Analytics Query: 39_inactive_vs_active.sql
WITH StatusCounts AS (SELECT is_active, COUNT(*) as cnt FROM fact_jobs GROUP BY is_active) SELECT * FROM StatusCounts;
