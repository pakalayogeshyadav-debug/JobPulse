-- =============================================================================
-- JobPulse Data Warehouse — Star Schema Definition
-- File: sql/schema/01_create_warehouse_schema.sql
--
-- Purpose:
--   Creates the Analytics Data Warehouse schema (Kimball Star Schema).
--   This layer sits on top of the operational ETL tables (data_sources, jobs, pipeline_runs).
--
-- Dimensions:
--   - dim_date (Surrogate Key, static)
--   - dim_company (Surrogate Key, Type 1 SCD)
--   - dim_location (Surrogate Key, Type 1 SCD)
--   - dim_skill (Surrogate Key, Type 1 SCD)
--
-- Facts & Bridges:
--   - fact_jobs (Central Fact Table)
--   - bridge_job_skill (Many-to-Many resolution)
--
-- Notes:
--   - 'pipeline_runs' and 'data_sources' are referenced from the operational schema.
--   - Surrogate keys (sk_*) are used for all dimensions.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. DIMENSION: dim_date
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.dim_date (
    sk_date_id          INTEGER PRIMARY KEY,      -- Format: YYYYMMDD
    full_date           DATE NOT NULL UNIQUE,
    day_of_week         SMALLINT NOT NULL,        -- 1=Monday, 7=Sunday
    day_name            VARCHAR(10) NOT NULL,
    day_of_month        SMALLINT NOT NULL,
    day_of_year         SMALLINT NOT NULL,
    is_weekend          BOOLEAN NOT NULL,
    week_of_year        SMALLINT NOT NULL,
    month_number        SMALLINT NOT NULL,
    month_name          VARCHAR(15) NOT NULL,
    quarter_number      SMALLINT NOT NULL,
    year_number         SMALLINT NOT NULL,
    is_holiday          BOOLEAN NOT NULL DEFAULT FALSE,
    holiday_name        VARCHAR(100)
);
COMMENT ON TABLE public.dim_date IS 'Conformed Date Dimension for time-series analytics.';

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. DIMENSION: dim_company
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.dim_company (
    sk_company_id       SERIAL PRIMARY KEY,       -- Surrogate Key
    company_name        VARCHAR(500) NOT NULL UNIQUE, -- Natural Key
    industry            VARCHAR(200),
    company_size        VARCHAR(100),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE public.dim_company IS 'Dimension: Companies hiring. Uses Type 1 SCD (Overwrite).';

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. DIMENSION: dim_location
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.dim_location (
    sk_location_id      SERIAL PRIMARY KEY,       -- Surrogate Key
    location_raw        VARCHAR(500) NOT NULL UNIQUE, -- Natural Key
    city                VARCHAR(200),
    state               VARCHAR(200),
    country             VARCHAR(200),
    is_remote           BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE public.dim_location IS 'Dimension: Job Locations. Uses Type 1 SCD (Overwrite).';

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. DIMENSION: dim_skill
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.dim_skill (
    sk_skill_id         SERIAL PRIMARY KEY,       -- Surrogate Key
    skill_name          VARCHAR(200) NOT NULL UNIQUE, -- Natural Key
    skill_category      VARCHAR(200),             -- e.g., 'Cloud', 'Data Engineering', 'Languages'
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE public.dim_skill IS 'Dimension: Standardised Skills. Uses Type 1 SCD (Overwrite).';

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. FACT TABLE: fact_jobs
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.fact_jobs (
    sk_fact_job_id      SERIAL PRIMARY KEY,
    
    -- Degenerate Dimension (Operational ID)
    job_id              INTEGER NOT NULL UNIQUE,  
    
    -- Dimension Foreign Keys
    sk_company_id       INTEGER NOT NULL,
    sk_location_id      INTEGER NOT NULL,
    sk_posted_date_id   INTEGER NOT NULL,
    
    -- Operational Conformed Dimensions (from public schema)
    data_source_id      INTEGER NOT NULL,
    pipeline_run_id     INTEGER,
    
    -- Descriptive Attributes
    job_title           VARCHAR(500) NOT NULL,
    work_arrangement    VARCHAR(50) NOT NULL,
    
    -- Facts / Measures
    salary_min          NUMERIC(12, 2),
    salary_max          NUMERIC(12, 2),
    salary_currency     VARCHAR(3),
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    
    -- Audit Timestamps
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT fk_fact_company FOREIGN KEY (sk_company_id) REFERENCES public.dim_company(sk_company_id) ON DELETE RESTRICT,
    CONSTRAINT fk_fact_location FOREIGN KEY (sk_location_id) REFERENCES public.dim_location(sk_location_id) ON DELETE RESTRICT,
    CONSTRAINT fk_fact_date FOREIGN KEY (sk_posted_date_id) REFERENCES public.dim_date(sk_date_id) ON DELETE RESTRICT,
    CONSTRAINT fk_fact_data_source FOREIGN KEY (data_source_id) REFERENCES public.data_sources(data_source_id) ON DELETE RESTRICT,
    CONSTRAINT fk_fact_pipeline_run FOREIGN KEY (pipeline_run_id) REFERENCES public.pipeline_runs(run_id) ON DELETE SET NULL,
    
    CONSTRAINT chk_fact_salary CHECK (salary_min <= salary_max)
);
COMMENT ON TABLE public.fact_jobs IS 'Core Fact Table: One row per verified job posting.';

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. BRIDGE TABLE: bridge_job_skill
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.bridge_job_skill (
    sk_fact_job_id      INTEGER NOT NULL,
    sk_skill_id         INTEGER NOT NULL,
    
    -- Audit Timestamp
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (sk_fact_job_id, sk_skill_id),
    CONSTRAINT fk_bridge_job FOREIGN KEY (sk_fact_job_id) REFERENCES public.fact_jobs(sk_fact_job_id) ON DELETE CASCADE,
    CONSTRAINT fk_bridge_skill FOREIGN KEY (sk_skill_id) REFERENCES public.dim_skill(sk_skill_id) ON DELETE CASCADE
);
COMMENT ON TABLE public.bridge_job_skill IS 'Bridge Table: Resolves Many-to-Many relationship between Jobs and Skills.';
