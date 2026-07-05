-- =============================================================================
-- JobPulse Data Engineering Pipeline
-- File        : sql/schema/schema.sql
-- Author      : Senior Data Engineer
-- Version     : 1.0.0
-- Created     : 2026-06-29
-- Description : Production-ready PostgreSQL schema in Third Normal Form (3NF)
--               for storing job market data from multiple public sources.
--
-- Design Goals:
--   • 3NF normalisation — eliminates all transitive dependencies
--   • Every table has a single, clear responsibility
--   • All foreign keys are explicitly declared and indexed
--   • Constraints enforce data integrity at the database layer
--   • Audit columns (created_at, updated_at) on every mutable table
--   • Partial, composite, and expression indexes for query performance
--
-- Execution:
--   psql -U jobpulse_user -d jobpulse_dw -f sql/schema/schema.sql
--
-- Order of creation (respects FK dependencies):
--   1.  data_sources        (no dependencies)
--   2.  locations           (no dependencies)
--   3.  companies           (no dependencies)
--   4.  employment_types    (no dependencies)
--   5.  experience_levels   (no dependencies)
--   6.  skills              (no dependencies)
--   7.  pipeline_runs       (→ data_sources)
--   8.  jobs                (→ companies, locations, employment_types,
--                              experience_levels, data_sources)
--   9.  salary_ranges       (→ jobs)
--   10. job_skills          (→ jobs, skills)
-- =============================================================================


-- ─────────────────────────────────────────────────────────────────────────────
-- HOUSEKEEPING
-- ─────────────────────────────────────────────────────────────────────────────

-- Drop tables in reverse dependency order for clean re-runs in development.
-- CAUTION: Never run DROP statements against production without a backup.
DROP TABLE IF EXISTS public.job_skills       CASCADE;
DROP TABLE IF EXISTS public.salary_ranges    CASCADE;
DROP TABLE IF EXISTS public.jobs             CASCADE;
DROP TABLE IF EXISTS public.pipeline_runs    CASCADE;
DROP TABLE IF EXISTS public.skills           CASCADE;
DROP TABLE IF EXISTS public.experience_levels CASCADE;
DROP TABLE IF EXISTS public.employment_types CASCADE;
DROP TABLE IF EXISTS public.companies        CASCADE;
DROP TABLE IF EXISTS public.locations        CASCADE;
DROP TABLE IF EXISTS public.data_sources     CASCADE;

-- Enable pg_trgm for trigram-based text search indexes (optional, requires superuser)
-- CREATE EXTENSION IF NOT EXISTS pg_trgm;


-- =============================================================================
-- TABLE 1: data_sources
-- =============================================================================
-- Stores the catalog of every external source from which job data is ingested.
-- This table is the "source of truth" for provenance tracking.
--
-- 3NF Rationale:
--   Without this table, source metadata (url, description) would be stored as
--   repeated string literals in the jobs table, violating 1NF/2NF.
--   All source attributes are functionally dependent solely on source_id.
--
-- Relationships:
--   • Referenced by: jobs.data_source_id, pipeline_runs.data_source_id
-- =============================================================================

CREATE TABLE public.data_sources (
    -- Surrogate primary key. Using SERIAL (auto-increment integer) keeps joins
    -- cheap. A natural key (source_name) would be fragile if names change.
    data_source_id   SERIAL          PRIMARY KEY,

    -- Short, machine-readable identifier used in ETL code (e.g., 'adzuna', 'usajobs')
    source_name      VARCHAR(100)    NOT NULL,

    -- Human-readable label for dashboards and reports
    display_name     VARCHAR(200)    NOT NULL,

    -- Root API or website URL of this data source
    base_url         VARCHAR(2048),

    -- Is the ETL pipeline currently configured to pull from this source?
    is_active        BOOLEAN         NOT NULL DEFAULT TRUE,

    -- Free-text notes: API rate limits, data quality caveats, etc.
    notes            TEXT,

    created_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- ── CONSTRAINTS ──────────────────────────────────────────────────────────
    CONSTRAINT uq_data_sources_name UNIQUE (source_name)
);

COMMENT ON TABLE  public.data_sources                    IS 'Catalog of all external job data sources ingested by the pipeline.';
COMMENT ON COLUMN public.data_sources.source_name        IS 'Short machine-readable key used in ETL code (e.g., ''adzuna'').';
COMMENT ON COLUMN public.data_sources.is_active          IS 'When FALSE, the ETL pipeline skips this source.';


-- =============================================================================
-- TABLE 2: locations
-- =============================================================================
-- Normalised geographic dimension.
-- Separating location from the jobs table eliminates the repeated storage of
-- "New York | NY | US" for every job posting in that city.
--
-- 3NF Rationale:
--   In a denormalised design, city, state, and country would all sit in the
--   jobs row. But state is functionally determined by city (in most cases),
--   and country is functionally determined by state — a transitive dependency.
--   Moving geography to its own table eliminates this violation.
--
-- Relationships:
--   • Referenced by: companies.location_id, jobs.location_id
-- =============================================================================

CREATE TABLE public.locations (
    location_id      SERIAL          PRIMARY KEY,

    -- City name as it appears in postings (post-normalisation)
    city             VARCHAR(200),

    -- State, province, or region (ISO 3166-2 subdivision code preferred: e.g., 'NY')
    state_code       VARCHAR(10),

    -- Full state/province name for display
    state_name       VARCHAR(100),

    -- ISO 3166-1 alpha-2 country code (e.g., 'US', 'GB', 'IN')
    country_code     CHAR(2)         NOT NULL,

    -- Full country name for display
    country_name     VARCHAR(100)    NOT NULL,

    -- Some postings specify continent for broad-level analytics
    region           VARCHAR(100),

    created_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- ── CONSTRAINTS ──────────────────────────────────────────────────────────
    -- A location is uniquely identified by the combination of city + state + country.
    -- NULLs are allowed in city/state for country-only records.
    CONSTRAINT uq_locations_city_state_country
        UNIQUE (city, state_code, country_code),

    CONSTRAINT chk_locations_country_code_format
        CHECK (country_code ~ '^[A-Z]{2}$')
);

COMMENT ON TABLE  public.locations              IS 'Normalised geographic dimension table.';
COMMENT ON COLUMN public.locations.country_code IS 'ISO 3166-1 alpha-2 code. Must be exactly 2 uppercase letters.';
COMMENT ON COLUMN public.locations.state_code   IS 'ISO 3166-2 subdivision code (e.g., NY, CA).';


-- =============================================================================
-- TABLE 3: companies
-- =============================================================================
-- Employer dimension table.
-- Normalising company data prevents storing "Google | tech | 10001+" in
-- every job row for every Google posting — which could be thousands of rows.
--
-- 3NF Rationale:
--   company_size and industry are attributes of the company entity, not of
--   a specific job posting. Keeping them in the jobs table would mean updating
--   thousands of rows if a company changes its industry classification.
--
-- Relationships:
--   • companies.location_id → locations.location_id (HQ location)
--   • Referenced by: jobs.company_id
-- =============================================================================

CREATE TABLE public.companies (
    company_id       SERIAL          PRIMARY KEY,

    -- Company name as it appears in job postings (normalised casing)
    company_name     VARCHAR(500)    NOT NULL,

    -- Industry vertical classification (e.g., 'Technology', 'Finance', 'Healthcare')
    industry         VARCHAR(200),

    -- Headcount band (standardised: '1-10', '11-50', '51-200', '201-500',
    --                 '501-1000', '1001-5000', '5001-10000', '10001+')
    company_size     VARCHAR(20),

    -- HQ location (nullable: not all sources provide this)
    location_id      INT             REFERENCES public.locations (location_id)
                                     ON DELETE SET NULL
                                     ON UPDATE CASCADE,

    -- Official company website
    website_url      VARCHAR(2048),

    -- LinkedIn company page (useful for enrichment)
    linkedin_url     VARCHAR(2048),

    -- Indicates whether this company record has been manually verified/enriched
    is_verified      BOOLEAN         NOT NULL DEFAULT FALSE,

    created_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- ── CONSTRAINTS ──────────────────────────────────────────────────────────
    CONSTRAINT chk_companies_size_values CHECK (
        company_size IS NULL OR company_size IN (
            '1-10', '11-50', '51-200', '201-500',
            '501-1000', '1001-5000', '5001-10000', '10001+'
        )
    )
);

COMMENT ON TABLE  public.companies               IS 'Normalised employer/company dimension.';
COMMENT ON COLUMN public.companies.company_size  IS 'Headcount band. Values: 1-10, 11-50, 51-200, 201-500, 501-1000, 1001-5000, 5001-10000, 10001+';
COMMENT ON COLUMN public.companies.is_verified   IS 'TRUE if manually enriched/verified against an authoritative source.';


-- =============================================================================
-- TABLE 4: employment_types
-- =============================================================================
-- Small lookup/reference table for employment type classifications.
-- Examples: Full-time, Part-time, Contract, Internship, Freelance, Temporary
--
-- 3NF Rationale:
--   Storing employment type as a VARCHAR directly in the jobs table creates
--   multiple problems: free-text inconsistencies ('FT', 'Full Time', 'fulltime'),
--   no enforced vocabulary, and inability to join on type for analytics.
--   This lookup table enforces a controlled vocabulary via FK constraint.
--
-- Relationships:
--   • Referenced by: jobs.employment_type_id
-- =============================================================================

CREATE TABLE public.employment_types (
    employment_type_id   SERIAL      PRIMARY KEY,

    -- Machine-readable code used in ETL code (e.g., 'FULL_TIME')
    type_code            VARCHAR(50)  NOT NULL,

    -- Human-readable display label (e.g., 'Full-time')
    type_label           VARCHAR(100) NOT NULL,

    -- Optional description for documentation
    description          TEXT,

    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- ── CONSTRAINTS ──────────────────────────────────────────────────────────
    CONSTRAINT uq_employment_types_code  UNIQUE (type_code),
    CONSTRAINT uq_employment_types_label UNIQUE (type_label)
);

COMMENT ON TABLE  public.employment_types            IS 'Controlled vocabulary for employment type classifications.';
COMMENT ON COLUMN public.employment_types.type_code  IS 'Machine-readable code. Example values: FULL_TIME, PART_TIME, CONTRACT, INTERNSHIP, FREELANCE, TEMPORARY.';

-- Seed reference data (idempotent — safe to re-run)
INSERT INTO public.employment_types (type_code, type_label, description) VALUES
    ('FULL_TIME',   'Full-time',   'Standard permanent employment, typically 35-40 hours/week'),
    ('PART_TIME',   'Part-time',   'Employment for fewer hours than a standard full-time schedule'),
    ('CONTRACT',    'Contract',    'Fixed-term engagement, often through a staffing agency'),
    ('INTERNSHIP',  'Internship',  'Temporary position, typically for students or recent graduates'),
    ('FREELANCE',   'Freelance',   'Self-employed, project-based engagement'),
    ('TEMPORARY',   'Temporary',   'Short-term employment to cover a specific need')
ON CONFLICT (type_code) DO NOTHING;


-- =============================================================================
-- TABLE 5: experience_levels
-- =============================================================================
-- Lookup table for seniority/experience level classifications.
-- Examples: Entry Level, Mid-Level, Senior, Lead, Executive
--
-- 3NF Rationale:
--   Same argument as employment_types. Experience level labels vary widely
--   across sources ('Junior', 'Entry Level', '0-2 years'). A normalised
--   lookup table with a controlled vocabulary allows consistent analytics.
--
-- Relationships:
--   • Referenced by: jobs.experience_level_id
-- =============================================================================

CREATE TABLE public.experience_levels (
    experience_level_id  SERIAL      PRIMARY KEY,

    -- Machine-readable code (e.g., 'MID_LEVEL')
    level_code           VARCHAR(50)  NOT NULL,

    -- Human-readable display label (e.g., 'Mid-Level')
    level_label          VARCHAR(100) NOT NULL,

    -- Typical years of experience associated with this level
    min_years_experience SMALLINT,
    max_years_experience SMALLINT,

    -- Sort order for dashboards (Entry=1, ..., Executive=5)
    sort_order           SMALLINT     NOT NULL DEFAULT 0,

    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- ── CONSTRAINTS ──────────────────────────────────────────────────────────
    CONSTRAINT uq_experience_levels_code  UNIQUE (level_code),
    CONSTRAINT uq_experience_levels_label UNIQUE (level_label),
    CONSTRAINT chk_experience_years_range CHECK (
        min_years_experience IS NULL
        OR max_years_experience IS NULL
        OR min_years_experience <= max_years_experience
    )
);

COMMENT ON TABLE  public.experience_levels              IS 'Controlled vocabulary for experience/seniority level classifications.';
COMMENT ON COLUMN public.experience_levels.sort_order   IS 'Display order: 1=Entry, 2=Mid, 3=Senior, 4=Lead, 5=Executive.';

-- Seed reference data
INSERT INTO public.experience_levels
    (level_code, level_label, min_years_experience, max_years_experience, sort_order)
VALUES
    ('ENTRY',     'Entry Level',  0,    2,    1),
    ('MID',       'Mid-Level',    2,    5,    2),
    ('SENIOR',    'Senior',       5,    10,   3),
    ('LEAD',      'Lead',         8,    15,   4),
    ('EXECUTIVE', 'Executive',    12,   NULL, 5)
ON CONFLICT (level_code) DO NOTHING;


-- =============================================================================
-- TABLE 6: skills
-- =============================================================================
-- Master catalog of all technical and soft skills extracted from job postings.
-- This is a slowly-changing dimension — new skills are added as they appear,
-- but existing skills rarely change.
--
-- 3NF Rationale:
--   Skills appear in a many-to-many relationship with jobs (one job requires
--   many skills; one skill appears in many jobs). Storing skills as a
--   comma-separated string in the jobs table violates 1NF. The correct
--   3NF design uses a normalised skills table + job_skills junction table.
--
-- Relationships:
--   • Referenced by: job_skills.skill_id (many-to-many with jobs)
-- =============================================================================

CREATE TABLE public.skills (
    skill_id         SERIAL          PRIMARY KEY,

    -- Canonical skill name, normalised (e.g., 'Python', 'Apache Spark', 'dbt')
    skill_name       VARCHAR(200)    NOT NULL,

    -- Skill category for grouping in analytics
    -- Examples: 'Programming Language', 'Cloud Platform', 'Database',
    --           'Framework', 'Tool', 'Soft Skill', 'Methodology'
    skill_category   VARCHAR(100),

    -- Alias list for normalisation (e.g., 'py' → 'Python')
    -- Stored as a pipe-separated string for simplicity at this stage.
    -- Consider a separate skill_aliases table at higher data volumes.
    aliases          TEXT,

    -- Whether this skill is actively tracked / in use
    is_active        BOOLEAN         NOT NULL DEFAULT TRUE,

    created_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- ── CONSTRAINTS ──────────────────────────────────────────────────────────
    -- Case-insensitive unique constraint to prevent 'python' and 'Python'
    CONSTRAINT uq_skills_name UNIQUE (skill_name)
);

COMMENT ON TABLE  public.skills               IS 'Master catalog of skills extracted from job postings.';
COMMENT ON COLUMN public.skills.skill_name    IS 'Canonical, normalised skill name.';
COMMENT ON COLUMN public.skills.aliases       IS 'Pipe-separated list of known aliases for ETL normalisation.';
COMMENT ON COLUMN public.skills.skill_category IS 'Grouping: Programming Language | Cloud Platform | Database | Framework | Tool | Soft Skill | Methodology';


-- =============================================================================
-- TABLE 7: pipeline_runs
-- =============================================================================
-- Operational audit table. Records every ETL pipeline execution.
-- Critical for debugging failures, monitoring data freshness, and
-- building pipeline observability dashboards.
--
-- 3NF Rationale:
--   Pipeline execution metadata is an independent entity — it has nothing
--   to do with the job posting data model. Keeping it in a separate table
--   is both correct 3NF design and good operational practice.
--
-- Relationships:
--   • pipeline_runs.data_source_id → data_sources.data_source_id
-- =============================================================================

CREATE TABLE public.pipeline_runs (
    run_id               SERIAL      PRIMARY KEY,

    -- Which source was ingested in this run
    data_source_id       INT         NOT NULL
                                     REFERENCES public.data_sources (data_source_id)
                                     ON DELETE RESTRICT
                                     ON UPDATE CASCADE,

    -- Pipeline execution status
    status               VARCHAR(20) NOT NULL DEFAULT 'RUNNING',

    -- UTC timestamps for the run lifecycle
    started_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at         TIMESTAMPTZ,

    -- Row-level metrics
    rows_extracted       INT,
    rows_transformed     INT,
    rows_loaded          INT,
    rows_rejected        INT,

    -- Duration in seconds (computed at pipeline completion)
    duration_seconds     NUMERIC(10, 2),

    -- Error details if status = 'FAILED'
    error_message        TEXT,
    error_traceback      TEXT,

    -- The git commit SHA of the pipeline code that ran this job (for reproducibility)
    pipeline_version     VARCHAR(40),

    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- ── CONSTRAINTS ──────────────────────────────────────────────────────────
    CONSTRAINT chk_pipeline_runs_status CHECK (
        status IN ('RUNNING', 'SUCCESS', 'FAILED', 'PARTIAL')
    ),
    CONSTRAINT chk_pipeline_runs_completed_after_started CHECK (
        completed_at IS NULL OR completed_at >= started_at
    ),
    CONSTRAINT chk_pipeline_runs_row_counts_non_negative CHECK (
        (rows_extracted  IS NULL OR rows_extracted  >= 0) AND
        (rows_transformed IS NULL OR rows_transformed >= 0) AND
        (rows_loaded     IS NULL OR rows_loaded     >= 0) AND
        (rows_rejected   IS NULL OR rows_rejected   >= 0)
    )
);

COMMENT ON TABLE  public.pipeline_runs                 IS 'Operational audit log of every ETL pipeline execution.';
COMMENT ON COLUMN public.pipeline_runs.status          IS 'Lifecycle state: RUNNING | SUCCESS | FAILED | PARTIAL.';
COMMENT ON COLUMN public.pipeline_runs.pipeline_version IS 'Git commit SHA of the ETL code for reproducibility.';


-- =============================================================================
-- TABLE 8: jobs
-- =============================================================================
-- The central entity table of the schema.
-- Represents one job posting as published by one company on one data source.
--
-- 3NF Rationale:
--   All non-key columns here are directly and solely dependent on job_id.
--   Geographic data → locations table (city/state transitively depend on each other)
--   Company metadata → companies table (industry/size depend on the company, not the job)
--   Employment type  → employment_types table (avoids free-text inconsistency)
--   Experience level → experience_levels table (avoids free-text inconsistency)
--   Salary data      → salary_ranges table (salary attributes depend on the salary offer,
--                       not the job identity — allows multiple salary records per job
--                       if a job is posted multiple times with different ranges)
--   Skills           → job_skills junction table (many-to-many)
--
-- Relationships:
--   • jobs.company_id           → companies.company_id
--   • jobs.location_id          → locations.location_id
--   • jobs.employment_type_id   → employment_types.employment_type_id
--   • jobs.experience_level_id  → experience_levels.experience_level_id
--   • jobs.data_source_id       → data_sources.data_source_id
--   • jobs.pipeline_run_id      → pipeline_runs.run_id
--   • Referenced by: salary_ranges.job_id, job_skills.job_id
-- =============================================================================

CREATE TABLE public.jobs (
    job_id               SERIAL          PRIMARY KEY,

    -- ── SOURCE PROVENANCE ─────────────────────────────────────────────────────
    -- Unique identifier for this posting from the originating source (API ID, URL hash, etc.)
    source_job_id        VARCHAR(500)    NOT NULL,

    -- Which ETL source produced this record
    data_source_id       INT             NOT NULL
                                         REFERENCES public.data_sources (data_source_id)
                                         ON DELETE RESTRICT
                                         ON UPDATE CASCADE,

    -- Which pipeline run created/last updated this record
    pipeline_run_id      INT
                                         REFERENCES public.pipeline_runs (run_id)
                                         ON DELETE SET NULL
                                         ON UPDATE CASCADE,

    -- ── CORE JOB ATTRIBUTES ───────────────────────────────────────────────────
    -- Job title as published (post-normalisation by the ETL transformer)
    job_title            VARCHAR(500)    NOT NULL,

    -- Canonical job title after classification (e.g., 'Data Engineer')
    -- This may differ from job_title due to normalisation
    canonical_title      VARCHAR(200),

    -- ── FOREIGN KEY REFERENCES TO DIMENSION TABLES ───────────────────────────
    company_id           INT             REFERENCES public.companies (company_id)
                                         ON DELETE SET NULL
                                         ON UPDATE CASCADE,

    -- Primary work location (NULL for fully remote with no stated location)
    location_id          INT             REFERENCES public.locations (location_id)
                                         ON DELETE SET NULL
                                         ON UPDATE CASCADE,

    employment_type_id   INT             REFERENCES public.employment_types (employment_type_id)
                                         ON DELETE SET NULL
                                         ON UPDATE CASCADE,

    experience_level_id  INT             REFERENCES public.experience_levels (experience_level_id)
                                         ON DELETE SET NULL
                                         ON UPDATE CASCADE,

    -- ── WORK ARRANGEMENT ──────────────────────────────────────────────────────
    -- TRUE = fully remote, FALSE = on-site/hybrid, NULL = not specified
    is_remote            BOOLEAN,

    -- More granular work arrangement (REMOTE | HYBRID | ON_SITE | UNSPECIFIED)
    work_arrangement     VARCHAR(20)     DEFAULT 'UNSPECIFIED',

    -- ── CONTENT ───────────────────────────────────────────────────────────────
    -- Full raw job description text (large, kept for keyword extraction)
    description          TEXT,

    -- Direct URL to the job posting on the source website
    posting_url          VARCHAR(2048),

    -- ── LIFECYCLE ─────────────────────────────────────────────────────────────
    -- Date the posting went live on the source (from API/parsing, not ingestion time)
    posted_date          DATE,

    -- If the posting has an explicit close/expiry date
    expiry_date          DATE,

    -- Whether this posting is currently live and open
    is_active            BOOLEAN         NOT NULL DEFAULT TRUE,

    -- Date when we confirmed the posting was no longer active
    closed_date          DATE,

    -- ── AUDIT ─────────────────────────────────────────────────────────────────
    created_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- ── CONSTRAINTS ───────────────────────────────────────────────────────────
    -- Business key: one posting per source_job_id per source
    CONSTRAINT uq_jobs_source_job_id_per_source
        UNIQUE (source_job_id, data_source_id),

    CONSTRAINT chk_jobs_work_arrangement CHECK (
        work_arrangement IN ('REMOTE', 'HYBRID', 'ON_SITE', 'UNSPECIFIED')
    ),

    CONSTRAINT chk_jobs_expiry_after_posted CHECK (
        expiry_date IS NULL OR posted_date IS NULL OR expiry_date >= posted_date
    ),

    CONSTRAINT chk_jobs_closed_date_when_inactive CHECK (
        is_active = TRUE OR closed_date IS NOT NULL
    )
);

COMMENT ON TABLE  public.jobs                    IS 'Central entity table. One row per unique job posting per data source.';
COMMENT ON COLUMN public.jobs.source_job_id      IS 'Unique identifier from the originating source (API ID, URL hash). Part of the business key.';
COMMENT ON COLUMN public.jobs.job_title          IS 'Raw normalised title from the source.';
COMMENT ON COLUMN public.jobs.canonical_title    IS 'Standardised title after ETL classification (e.g., ''Data Engineer'').';
COMMENT ON COLUMN public.jobs.is_remote          IS 'TRUE=Remote, FALSE=On-site/Hybrid, NULL=Not specified.';
COMMENT ON COLUMN public.jobs.posted_date        IS 'Date the job went live on the source site (not ETL ingestion date).';
COMMENT ON COLUMN public.jobs.pipeline_run_id    IS 'FK to pipeline_runs. Tracks which ETL run last wrote this record.';


-- =============================================================================
-- TABLE 9: salary_ranges
-- =============================================================================
-- Salary information for a job posting, stored in a separate table.
--
-- Why separate from jobs?
--   1. A single job posting may have multiple salary records over time
--      if the posting is refreshed with an updated range.
--   2. Salary has its own complex attributes (currency, period, type) that
--      would otherwise balloon the jobs table width.
--   3. Separating salary allows nullable salary data without nullifying
--      important job columns (cleaner 3NF).
--   4. Salary analytics (avg, percentile) are simpler with a dedicated table.
--
-- 3NF Rationale:
--   currency_code → currency_name is a transitive dependency.
--   For this scale, we store currency_name inline but enforce the code.
--   At higher scale, extract a currencies lookup table.
--
-- Relationships:
--   • salary_ranges.job_id → jobs.job_id
-- =============================================================================

CREATE TABLE public.salary_ranges (
    salary_id        SERIAL          PRIMARY KEY,

    job_id           INT             NOT NULL
                                     REFERENCES public.jobs (job_id)
                                     ON DELETE CASCADE
                                     ON UPDATE CASCADE,

    -- ── SALARY VALUES ─────────────────────────────────────────────────────────
    -- Use NUMERIC for money — never FLOAT (floating point imprecision)
    salary_min       NUMERIC(14, 2),
    salary_max       NUMERIC(14, 2),

    -- Middle of the range (NULL if only one bound given)
    salary_midpoint  NUMERIC(14, 2)  GENERATED ALWAYS AS (
                         CASE
                             WHEN salary_min IS NOT NULL AND salary_max IS NOT NULL
                             THEN ROUND((salary_min + salary_max) / 2.0, 2)
                             ELSE NULL
                         END
                     ) STORED,

    -- ── SALARY METADATA ───────────────────────────────────────────────────────
    -- ISO 4217 currency code (e.g., 'USD', 'GBP', 'EUR', 'INR')
    currency_code    CHAR(3)         NOT NULL DEFAULT 'USD',

    -- Pay period granularity
    salary_period    VARCHAR(20)     NOT NULL DEFAULT 'ANNUAL',

    -- Salary type (some postings distinguish base from total compensation)
    salary_type      VARCHAR(20)     DEFAULT 'BASE',

    -- Was this salary explicitly stated, or estimated/inferred by the source?
    is_estimated     BOOLEAN         NOT NULL DEFAULT FALSE,

    created_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- ── CONSTRAINTS ───────────────────────────────────────────────────────────
    CONSTRAINT chk_salary_min_max CHECK (
        salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max
    ),
    CONSTRAINT chk_salary_non_negative CHECK (
        (salary_min IS NULL OR salary_min >= 0) AND
        (salary_max IS NULL OR salary_max >= 0)
    ),
    CONSTRAINT chk_salary_period CHECK (
        salary_period IN ('HOURLY', 'DAILY', 'WEEKLY', 'MONTHLY', 'ANNUAL')
    ),
    CONSTRAINT chk_salary_type CHECK (
        salary_type IN ('BASE', 'TOTAL_COMP', 'OTE', 'UNSPECIFIED')
    ),
    CONSTRAINT chk_currency_code_format CHECK (
        currency_code ~ '^[A-Z]{3}$'
    ),
    -- Every salary row must have at least one bound
    CONSTRAINT chk_salary_at_least_one_bound CHECK (
        salary_min IS NOT NULL OR salary_max IS NOT NULL
    )
);

COMMENT ON TABLE  public.salary_ranges                  IS 'Salary information for job postings. Separated from jobs for normalisation and versioning.';
COMMENT ON COLUMN public.salary_ranges.salary_midpoint  IS 'Computed column: (min+max)/2. NULL if only one bound present.';
COMMENT ON COLUMN public.salary_ranges.salary_period    IS 'Granularity: HOURLY | DAILY | WEEKLY | MONTHLY | ANNUAL.';
COMMENT ON COLUMN public.salary_ranges.is_estimated     IS 'TRUE if the salary was inferred/estimated, not explicitly stated.';
COMMENT ON COLUMN public.salary_ranges.currency_code    IS 'ISO 4217 three-letter currency code (must be uppercase).';


-- =============================================================================
-- TABLE 10: job_skills
-- =============================================================================
-- Junction/bridge table resolving the many-to-many relationship between
-- jobs and skills.
--
-- 3NF Rationale:
--   A job requires many skills; a skill appears in many jobs.
--   This cannot be represented in a single table without either:
--   (a) repeating job rows for each skill — violates 1NF, or
--   (b) storing skills as a comma-separated string — violates 1NF.
--   The junction table is the canonical 3NF solution.
--
-- Extended Attributes on the Junction:
--   Adding context attributes (is_required, proficiency_level) on the
--   junction itself is correct 3NF — these attributes describe the
--   relationship between a specific job and a specific skill, not
--   either entity alone.
--
-- Relationships:
--   • job_skills.job_id   → jobs.job_id
--   • job_skills.skill_id → skills.skill_id
-- =============================================================================

CREATE TABLE public.job_skills (
    job_skill_id         SERIAL          PRIMARY KEY,

    job_id               INT             NOT NULL
                                         REFERENCES public.jobs (job_id)
                                         ON DELETE CASCADE
                                         ON UPDATE CASCADE,

    skill_id             INT             NOT NULL
                                         REFERENCES public.skills (skill_id)
                                         ON DELETE CASCADE
                                         ON UPDATE CASCADE,

    -- Is this skill explicitly required (vs. "nice to have" / preferred)?
    is_required          BOOLEAN         NOT NULL DEFAULT TRUE,

    -- Optional proficiency expectation stated in the posting
    -- Values: BEGINNER | INTERMEDIATE | ADVANCED | EXPERT
    proficiency_level    VARCHAR(20),

    -- How the skill appeared in the source text (useful for NLP/ML training)
    extracted_text       VARCHAR(500),

    created_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- ── CONSTRAINTS ───────────────────────────────────────────────────────────
    -- A skill can only appear once per job
    CONSTRAINT uq_job_skills_job_skill UNIQUE (job_id, skill_id),

    CONSTRAINT chk_job_skills_proficiency CHECK (
        proficiency_level IS NULL OR
        proficiency_level IN ('BEGINNER', 'INTERMEDIATE', 'ADVANCED', 'EXPERT')
    )
);

COMMENT ON TABLE  public.job_skills                     IS 'Junction table resolving the many-to-many relationship between jobs and skills.';
COMMENT ON COLUMN public.job_skills.is_required         IS 'TRUE = explicitly required; FALSE = preferred/nice-to-have.';
COMMENT ON COLUMN public.job_skills.proficiency_level   IS 'Skill proficiency expectation: BEGINNER | INTERMEDIATE | ADVANCED | EXPERT.';
COMMENT ON COLUMN public.job_skills.extracted_text      IS 'Raw text fragment from posting used to identify this skill (useful for NLP training data).';


-- =============================================================================
-- INDEXES
-- =============================================================================
-- PostgreSQL does NOT auto-create indexes on foreign key columns.
-- Without indexes on FK columns, every JOIN scans the entire child table.
-- Rule: Index every foreign key + every column that appears in WHERE clauses
--       of common analytical queries.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- jobs table indexes
-- ─────────────────────────────────────────────────────────────────────────────

-- FK index: jobs → companies
-- Without this, "SELECT * FROM jobs WHERE company_id = 42" does a full scan.
CREATE INDEX ix_jobs_company_id
    ON public.jobs (company_id);
COMMENT ON INDEX public.ix_jobs_company_id IS 'FK lookup: jobs belonging to a specific company.';

-- FK index: jobs → locations
CREATE INDEX ix_jobs_location_id
    ON public.jobs (location_id);
COMMENT ON INDEX public.ix_jobs_location_id IS 'FK lookup: jobs in a specific location.';

-- FK index: jobs → employment_types
CREATE INDEX ix_jobs_employment_type_id
    ON public.jobs (employment_type_id);
COMMENT ON INDEX public.ix_jobs_employment_type_id IS 'FK lookup: jobs by employment type.';

-- FK index: jobs → experience_levels
CREATE INDEX ix_jobs_experience_level_id
    ON public.jobs (experience_level_id);
COMMENT ON INDEX public.ix_jobs_experience_level_id IS 'FK lookup: jobs by experience level.';

-- FK index: jobs → data_sources
CREATE INDEX ix_jobs_data_source_id
    ON public.jobs (data_source_id);
COMMENT ON INDEX public.ix_jobs_data_source_id IS 'FK lookup: jobs from a specific data source.';

-- FK index: jobs → pipeline_runs
CREATE INDEX ix_jobs_pipeline_run_id
    ON public.jobs (pipeline_run_id);
COMMENT ON INDEX public.ix_jobs_pipeline_run_id IS 'FK lookup: all jobs loaded in a specific pipeline run.';

-- Analytical index: hiring trends over time
-- Powers: "SELECT COUNT(*), posted_date FROM jobs GROUP BY posted_date"
CREATE INDEX ix_jobs_posted_date
    ON public.jobs (posted_date DESC NULLS LAST);
COMMENT ON INDEX public.ix_jobs_posted_date IS 'Time-series queries: hiring trends over time.';

-- Partial index: only active job postings (covers ~80% of analytical queries)
-- A partial index is smaller than a full index and faster for common filters.
CREATE INDEX ix_jobs_is_active_partial
    ON public.jobs (is_active)
    WHERE is_active = TRUE;
COMMENT ON INDEX public.ix_jobs_is_active_partial IS 'Partial index for active jobs only. Smaller and faster than a full is_active index.';

-- Composite index: remote jobs by date (covers "Show remote jobs this month")
CREATE INDEX ix_jobs_is_remote_posted_date
    ON public.jobs (is_remote, posted_date DESC NULLS LAST)
    WHERE is_remote = TRUE;
COMMENT ON INDEX public.ix_jobs_is_remote_posted_date IS 'Composite partial index: remote job trend analysis.';

-- Text search index on canonical_title for fast filtering in Power BI
-- Supports: WHERE canonical_title = 'Data Engineer'
CREATE INDEX ix_jobs_canonical_title
    ON public.jobs (canonical_title);
COMMENT ON INDEX public.ix_jobs_canonical_title IS 'Supports analytics segmented by canonical job title.';


-- ─────────────────────────────────────────────────────────────────────────────
-- salary_ranges table indexes
-- ─────────────────────────────────────────────────────────────────────────────

-- FK index: salary_ranges → jobs
CREATE INDEX ix_salary_ranges_job_id
    ON public.salary_ranges (job_id);
COMMENT ON INDEX public.ix_salary_ranges_job_id IS 'FK lookup: salary record(s) for a specific job.';

-- Analytical index: salary distribution and trend queries
-- Powers: "AVG(salary_midpoint) GROUP BY currency_code, salary_period"
CREATE INDEX ix_salary_ranges_midpoint_currency
    ON public.salary_ranges (salary_midpoint, currency_code, salary_period)
    WHERE salary_midpoint IS NOT NULL;
COMMENT ON INDEX public.ix_salary_ranges_midpoint_currency IS 'Salary distribution analytics. Partial: only rows with a computable midpoint.';


-- ─────────────────────────────────────────────────────────────────────────────
-- job_skills table indexes
-- ─────────────────────────────────────────────────────────────────────────────

-- FK index: job_skills → jobs
-- Already covered by the composite UNIQUE constraint (job_id, skill_id)
-- which implicitly creates a btree index. But an explicit single-column
-- index helps for queries like "DELETE FROM job_skills WHERE job_id = ?"
CREATE INDEX ix_job_skills_job_id
    ON public.job_skills (job_id);
COMMENT ON INDEX public.ix_job_skills_job_id IS 'FK lookup and cascade delete support.';

-- FK index: job_skills → skills
-- Powers: "SELECT COUNT(DISTINCT job_id) FROM job_skills WHERE skill_id = 7"
-- (Most in-demand skills query)
CREATE INDEX ix_job_skills_skill_id
    ON public.job_skills (skill_id);
COMMENT ON INDEX public.ix_job_skills_skill_id IS 'Most critical index: powers ''most in-demand skills'' analytics.';

-- Partial index for required skills only
-- Powers: "Top required skills" (filters out optional/preferred skills)
CREATE INDEX ix_job_skills_required_skill_id
    ON public.job_skills (skill_id)
    WHERE is_required = TRUE;
COMMENT ON INDEX public.ix_job_skills_required_skill_id IS 'Partial index: most in-demand REQUIRED skills queries.';


-- ─────────────────────────────────────────────────────────────────────────────
-- companies table indexes
-- ─────────────────────────────────────────────────────────────────────────────

-- FK index: companies → locations
CREATE INDEX ix_companies_location_id
    ON public.companies (location_id);
COMMENT ON INDEX public.ix_companies_location_id IS 'FK lookup: companies headquartered in a given location.';

-- Analytical index: top hiring companies by industry
CREATE INDEX ix_companies_industry
    ON public.companies (industry)
    WHERE industry IS NOT NULL;
COMMENT ON INDEX public.ix_companies_industry IS 'Supports industry-level company aggregations.';


-- ─────────────────────────────────────────────────────────────────────────────
-- pipeline_runs table indexes
-- ─────────────────────────────────────────────────────────────────────────────

-- FK index: pipeline_runs → data_sources
CREATE INDEX ix_pipeline_runs_data_source_id
    ON public.pipeline_runs (data_source_id);
COMMENT ON INDEX public.ix_pipeline_runs_data_source_id IS 'FK lookup: all runs for a given data source.';

-- Monitoring: find recent failed runs quickly
CREATE INDEX ix_pipeline_runs_status_started
    ON public.pipeline_runs (status, started_at DESC)
    WHERE status = 'FAILED';
COMMENT ON INDEX public.ix_pipeline_runs_status_started IS 'Partial index: fast lookup of failed pipeline runs for alerting.';


-- ─────────────────────────────────────────────────────────────────────────────
-- skills table indexes
-- ─────────────────────────────────────────────────────────────────────────────

-- Supports ETL normalisation lookups: "SELECT skill_id WHERE skill_name = 'Python'"
-- Note: The UNIQUE constraint already creates a btree index on skill_name.
-- Add a category index for group-by queries:
CREATE INDEX ix_skills_category
    ON public.skills (skill_category)
    WHERE skill_category IS NOT NULL;
COMMENT ON INDEX public.ix_skills_category IS 'Supports aggregations by skill category (e.g., ''Programming Language'' demand).';


-- =============================================================================
-- UPDATED_AT TRIGGER FUNCTION
-- =============================================================================
-- Automatically maintains the updated_at column on every UPDATE operation.
-- Without this, updated_at only changes if the ETL code explicitly sets it.
-- =============================================================================

CREATE OR REPLACE FUNCTION public.fn_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    -- Set updated_at to the current UTC timestamp on any UPDATE
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION public.fn_set_updated_at() IS
    'Trigger function: automatically sets updated_at = NOW() on UPDATE.';

-- ── Attach the trigger to every table with an updated_at column ──────────────

CREATE TRIGGER trg_data_sources_updated_at
    BEFORE UPDATE ON public.data_sources
    FOR EACH ROW EXECUTE FUNCTION public.fn_set_updated_at();

CREATE TRIGGER trg_locations_updated_at
    BEFORE UPDATE ON public.locations
    FOR EACH ROW EXECUTE FUNCTION public.fn_set_updated_at();

CREATE TRIGGER trg_companies_updated_at
    BEFORE UPDATE ON public.companies
    FOR EACH ROW EXECUTE FUNCTION public.fn_set_updated_at();

CREATE TRIGGER trg_skills_updated_at
    BEFORE UPDATE ON public.skills
    FOR EACH ROW EXECUTE FUNCTION public.fn_set_updated_at();

CREATE TRIGGER trg_jobs_updated_at
    BEFORE UPDATE ON public.jobs
    FOR EACH ROW EXECUTE FUNCTION public.fn_set_updated_at();

CREATE TRIGGER trg_salary_ranges_updated_at
    BEFORE UPDATE ON public.salary_ranges
    FOR EACH ROW EXECUTE FUNCTION public.fn_set_updated_at();


-- =============================================================================
-- VERIFICATION QUERIES
-- Run these after executing the schema to confirm correct creation.
-- =============================================================================

-- List all tables in public schema
-- SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;

-- List all indexes
-- SELECT indexname, tablename, indexdef FROM pg_indexes
-- WHERE schemaname = 'public' ORDER BY tablename, indexname;

-- List all foreign keys
-- SELECT conname, conrelid::regclass AS table, confrelid::regclass AS references
-- FROM pg_constraint WHERE contype = 'f' ORDER BY table;

-- Count rows per table (after seeding)
-- SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname;


-- =============================================================================
-- END OF SCHEMA
-- =============================================================================
