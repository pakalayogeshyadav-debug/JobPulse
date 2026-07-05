-- Analytics Query: 16_jobs_by_source.sql
SELECT ds.source_name, COUNT(*) FROM fact_jobs f JOIN data_sources ds ON f.data_source_id = ds.data_source_id GROUP BY ds.source_name;
