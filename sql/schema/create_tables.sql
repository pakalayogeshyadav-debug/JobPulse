-- =============================================================================
-- JobPulse Data Warehouse — Schema Definition (Phase 1)
-- sql/schema/create_tables.sql
--
-- Purpose:
--   DDL script to create core tables in the jobpulse_dw PostgreSQL database.
--   This is the SQL equivalent of the simplified SQLAlchemy ORM models.
--
-- Tables:
--   1. data_sources
--   2. pipeline_runs
--   3. jobs
-- =============================================================================

-- =============================================================================
-- Table: data_sources
-- =============================================================================
CREATE TABLE IF NOT EXISTS public.data_sources (
    data_source_id   SERIAL PRIMARY KEY,
    source_name      VARCHAR(100) NOT NULL UNIQUE,
    display_name     VARCHAR(200) NOT NULL,
    base_url         VARCHAR(2048),
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.data_sources IS 'Catalog of all external job data sources.';

-- =============================================================================
-- Table: pipeline_runs
-- =============================================================================
CREATE TABLE IF NOT EXISTS public.pipeline_runs (
    run_id           SERIAL PRIMARY KEY,
    data_source_id   INTEGER NOT NULL,
    status           VARCHAR(50) NOT NULL,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at     TIMESTAMPTZ,
    pipeline_version VARCHAR(50),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT chk_pipeline_runs_status CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED', 'PARTIAL'))
);

CREATE INDEX IF NOT EXISTS ix_pipeline_runs_data_source_id ON public.pipeline_runs(data_source_id);

COMMENT ON TABLE public.pipeline_runs IS 'Audit log of ETL pipeline executions.';

-- =============================================================================
-- Table: jobs (Core Fact Table)
-- =============================================================================
CREATE TABLE IF NOT EXISTS public.jobs (
    job_id           SERIAL PRIMARY KEY,
    
    -- Source provenance
    source_job_id    VARCHAR(500) NOT NULL,
    data_source_id   INTEGER NOT NULL,
    pipeline_run_id  INTEGER,
    
    -- Core job attributes
    job_title        VARCHAR(500) NOT NULL,
    
    -- Denormalized dimensions (Phase 1)
    company_name     VARCHAR(500),
    location_raw     VARCHAR(500),
    
    salary_min       NUMERIC(12, 2),
    salary_max       NUMERIC(12, 2),
    salary_currency  VARCHAR(3),
    
    -- Work arrangement
    is_remote        BOOLEAN,
    work_arrangement VARCHAR(20) NOT NULL DEFAULT 'UNSPECIFIED',
    
    -- Content
    description      TEXT,
    posting_url      VARCHAR(2048),
    
    -- Lifecycle
    posted_date      DATE,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    
    -- Audit Timestamps
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Foreign Keys
    CONSTRAINT fk_jobs_data_source FOREIGN KEY (data_source_id) REFERENCES public.data_sources(data_source_id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_jobs_pipeline_run FOREIGN KEY (pipeline_run_id) REFERENCES public.pipeline_runs(run_id) ON DELETE SET NULL ON UPDATE CASCADE,

    -- Unique Constraint
    CONSTRAINT uq_jobs_source_job_id_per_source UNIQUE (source_job_id, data_source_id),

    -- Check Constraints
    CONSTRAINT chk_jobs_salary_range CHECK (salary_min <= salary_max)
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS ix_jobs_data_source_id ON public.jobs (data_source_id);
CREATE INDEX IF NOT EXISTS ix_jobs_pipeline_run_id ON public.jobs (pipeline_run_id);
CREATE INDEX IF NOT EXISTS ix_jobs_posted_date ON public.jobs (posted_date);
CREATE INDEX IF NOT EXISTS ix_jobs_is_active ON public.jobs (is_active);

COMMENT ON TABLE public.jobs IS 'Central entity. One row per unique job posting per data source.';
