-- Analytics Query: 05_active_jobs.sql
SELECT COUNT(*) FROM fact_jobs WHERE is_active = TRUE;
