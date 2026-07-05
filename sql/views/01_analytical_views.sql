-- =============================================================================
-- JobPulse Data Warehouse — Analytical Views
-- File: sql/views/01_analytical_views.sql
--
-- Purpose:
--   Creates optimized views mapping the Star Schema for Power BI consumption.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. vw_salary_by_role
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.vw_salary_by_role AS
SELECT 
    f.job_title,
    COUNT(f.sk_fact_job_id) AS total_jobs,
    ROUND(AVG(f.salary_min), 2) AS avg_salary_min,
    ROUND(AVG(f.salary_max), 2) AS avg_salary_max,
    ROUND(AVG((f.salary_min + f.salary_max) / 2), 2) AS avg_salary_midpoint,
    MIN(f.salary_min) AS lowest_salary,
    MAX(f.salary_max) AS highest_salary,
    f.salary_currency
FROM public.fact_jobs f
WHERE f.salary_min IS NOT NULL 
  AND f.salary_max IS NOT NULL
GROUP BY 
    f.job_title, 
    f.salary_currency;
COMMENT ON VIEW public.vw_salary_by_role IS 'Aggregates salary statistics by job title.';

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. vw_top_skills
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.vw_top_skills AS
SELECT 
    s.skill_name,
    s.skill_category,
    COUNT(b.sk_fact_job_id) AS job_count,
    ROUND(COUNT(b.sk_fact_job_id) * 100.0 / (SELECT COUNT(*) FROM public.fact_jobs), 2) AS percentage_of_all_jobs
FROM public.dim_skill s
JOIN public.bridge_job_skill b ON s.sk_skill_id = b.sk_skill_id
GROUP BY 
    s.skill_name, 
    s.skill_category
ORDER BY job_count DESC;
COMMENT ON VIEW public.vw_top_skills IS 'Ranks skills by frequency of occurrence across all jobs.';

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. vw_remote_jobs
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.vw_remote_jobs AS
SELECT 
    d.year_number,
    d.month_number,
    d.month_name,
    l.is_remote,
    COUNT(f.sk_fact_job_id) AS total_jobs
FROM public.fact_jobs f
JOIN public.dim_location l ON f.sk_location_id = l.sk_location_id
JOIN public.dim_date d ON f.sk_posted_date_id = d.sk_date_id
GROUP BY 
    d.year_number,
    d.month_number,
    d.month_name,
    l.is_remote
ORDER BY d.year_number, d.month_number;
COMMENT ON VIEW public.vw_remote_jobs IS 'Time-series analysis of remote vs on-site roles.';

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. vw_jobs_by_location
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.vw_jobs_by_location AS
SELECT 
    l.city,
    l.state,
    l.country,
    COUNT(f.sk_fact_job_id) AS total_jobs,
    ROUND(AVG((f.salary_min + f.salary_max) / 2), 2) AS avg_salary_midpoint
FROM public.fact_jobs f
JOIN public.dim_location l ON f.sk_location_id = l.sk_location_id
WHERE l.city IS NOT NULL AND l.city != ''
GROUP BY 
    l.city, 
    l.state, 
    l.country
ORDER BY total_jobs DESC;
COMMENT ON VIEW public.vw_jobs_by_location IS 'Aggregates job volume and average salaries by geographic location.';

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. vw_company_hiring
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.vw_company_hiring AS
SELECT 
    c.company_name,
    c.industry,
    COUNT(f.sk_fact_job_id) AS active_postings,
    COUNT(DISTINCT f.job_title) AS unique_roles
FROM public.fact_jobs f
JOIN public.dim_company c ON f.sk_company_id = c.sk_company_id
WHERE f.is_active = TRUE
GROUP BY 
    c.company_name,
    c.industry
ORDER BY active_postings DESC;
COMMENT ON VIEW public.vw_company_hiring IS 'Ranks companies by volume of active job postings.';

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. vw_pipeline_health
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.vw_pipeline_health AS
SELECT 
    ds.source_name,
    COUNT(pr.run_id) AS total_runs,
    SUM(CASE WHEN pr.status = 'SUCCESS' THEN 1 ELSE 0 END) AS success_runs,
    SUM(CASE WHEN pr.status = 'FAILED' THEN 1 ELSE 0 END) AS failed_runs,
    SUM(CASE WHEN pr.status = 'PARTIAL' THEN 1 ELSE 0 END) AS partial_runs,
    ROUND(SUM(CASE WHEN pr.status = 'SUCCESS' THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(pr.run_id), 0), 2) AS success_rate,
    MAX(pr.completed_at) AS last_run_completed
FROM public.pipeline_runs pr
JOIN public.data_sources ds ON pr.data_source_id = ds.data_source_id
GROUP BY 
    ds.source_name;
COMMENT ON VIEW public.vw_pipeline_health IS 'Summarizes ETL pipeline execution metrics per data source.';
