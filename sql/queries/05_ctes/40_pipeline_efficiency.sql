-- Analytics Query: 40_pipeline_efficiency.sql
WITH RunStats AS (SELECT pipeline_run_id, COUNT(*) as loaded_rows FROM fact_jobs GROUP BY pipeline_run_id) SELECT pr.run_id, pr.status, rs.loaded_rows FROM pipeline_runs pr LEFT JOIN RunStats rs ON pr.run_id = rs.pipeline_run_id;
