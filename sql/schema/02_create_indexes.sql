-- =============================================================================
-- JobPulse Data Warehouse — Analytics Indexes
-- File: sql/schema/02_create_indexes.sql
--
-- Purpose:
--   Creates necessary B-Tree indexes on Foreign Keys and composite covering
--   indexes designed explicitly for Power BI analytics.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. FOREIGN KEY INDEXES (fact_jobs)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_fact_jobs_company_id ON public.fact_jobs(sk_company_id);
CREATE INDEX IF NOT EXISTS idx_fact_jobs_location_id ON public.fact_jobs(sk_location_id);
CREATE INDEX IF NOT EXISTS idx_fact_jobs_date_id ON public.fact_jobs(sk_posted_date_id);
CREATE INDEX IF NOT EXISTS idx_fact_jobs_data_source_id ON public.fact_jobs(data_source_id);
CREATE INDEX IF NOT EXISTS idx_fact_jobs_pipeline_run_id ON public.fact_jobs(pipeline_run_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. FOREIGN KEY INDEXES (bridge_job_skill)
-- ─────────────────────────────────────────────────────────────────────────────
-- Note: Primary key (sk_fact_job_id, sk_skill_id) acts as the index for job -> skill.
-- We need the reverse index for skill -> job queries (e.g. counting jobs per skill).
CREATE INDEX IF NOT EXISTS idx_bridge_skill_id ON public.bridge_job_skill(sk_skill_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. COVERING & COMPOSITE INDEXES FOR ANALYTICS VIEWS
-- ─────────────────────────────────────────────────────────────────────────────

-- Optimize: Salary filtering by role (e.g. vw_salary_by_role)
CREATE INDEX IF NOT EXISTS idx_fact_jobs_title_salary ON public.fact_jobs(job_title) INCLUDE (salary_min, salary_max);

-- Optimize: Time-series analysis (date filtering)
CREATE INDEX IF NOT EXISTS idx_dim_date_ymd ON public.dim_date(year_number, month_number, day_of_month);

-- Optimize: Location filtering
CREATE INDEX IF NOT EXISTS idx_dim_location_remote ON public.dim_location(is_remote, city);

-- Optimize: Active jobs
CREATE INDEX IF NOT EXISTS idx_fact_jobs_active ON public.fact_jobs(is_active) WHERE is_active = TRUE;
