-- =============================================================================
-- JobPulse Data Engineering Pipeline
-- File        : sql/views/analytics_views.sql
-- Purpose     : Materialized and regular views for BI layer consumption
-- Author      : Senior Data Engineer
-- Version     : 1.0.0
-- Database    : PostgreSQL 15+
--
-- Views defined:
--   MATERIALIZED  mv_company_stats         — Pre-aggregated company metrics
--   MATERIALIZED  mv_skill_demand          — Pre-aggregated skill demand
--   MATERIALIZED  mv_monthly_hiring_trend  — Monthly time-series (pre-computed)
--   MATERIALIZED  mv_salary_by_city        — City salary statistics
--   MATERIALIZED  mv_salary_by_skill       — Skill salary premium table
--   REGULAR VIEW  v_active_jobs            — Denormalised flat view of active jobs
--   REGULAR VIEW  v_job_skills_detail      — Job + skill with full context
--   REGULAR VIEW  v_pipeline_health        — Operational monitoring view
--
-- WHY MATERIALIZED VIEWS?
--   The analytical queries in analytics.sql run multi-table JOINs with window
--   functions and percentile aggregates over millions of rows. Running them
--   directly on every Power BI refresh (every 15–30 minutes) would put
--   unacceptable load on PostgreSQL.
--
--   Materialized views pre-compute the result and store it as a physical table.
--   Power BI queries the materialized view instead of the raw tables — a
--   single sequential scan of a small pre-computed table instead of a
--   multi-table JOIN over millions of rows.
--
--   Trade-off: data is slightly stale between refreshes.
--   Refresh strategy: REFRESH MATERIALIZED VIEW CONCURRENTLY after each
--   pipeline run (typically nightly). CONCURRENTLY means readers are not
--   blocked during refresh.
--
-- WHY REGULAR VIEWS FOR SOME?
--   v_active_jobs and v_job_skills_detail are used by the ETL loading layer
--   (conflict detection, deduplication). They must always return live data,
--   not stale pre-aggregations. Regular views always run against live tables.
--
-- REFRESH COMMANDS (run after each pipeline completion):
--   REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_company_stats;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_skill_demand;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_monthly_hiring_trend;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_salary_by_city;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_salary_by_skill;
--
-- Usage:
--   psql -d jobpulse_dw -f sql/views/analytics_views.sql
-- =============================================================================


-- =============================================================================
-- DROP EXISTING VIEWS (safe for re-runs in development)
-- Order: materialized views first, then regular views
-- =============================================================================

DROP MATERIALIZED VIEW IF EXISTS public.mv_salary_by_skill        CASCADE;
DROP MATERIALIZED VIEW IF EXISTS public.mv_salary_by_city         CASCADE;
DROP MATERIALIZED VIEW IF EXISTS public.mv_monthly_hiring_trend   CASCADE;
DROP MATERIALIZED VIEW IF EXISTS public.mv_skill_demand           CASCADE;
DROP MATERIALIZED VIEW IF EXISTS public.mv_company_stats          CASCADE;

DROP VIEW IF EXISTS public.v_pipeline_health    CASCADE;
DROP VIEW IF EXISTS public.v_job_skills_detail  CASCADE;
DROP VIEW IF EXISTS public.v_active_jobs        CASCADE;


-- =============================================================================
-- REGULAR VIEW 1: v_active_jobs
-- =============================================================================
-- PURPOSE:
--   Denormalised flat view of all currently active job postings.
--   Joins the 5 most-used dimension tables (company, location, employment_type,
--   experience_level, data_source) so BI consumers don't need to know the
--   schema's FK structure.
--
-- WHY REGULAR (NOT MATERIALIZED):
--   This view is used by the ETL loading layer for conflict detection
--   ("does this source_job_id already exist?"). It must always return
--   live, current data — not a potentially stale snapshot.
--   Power BI can also use this for detail drill-through pages.
--
-- PERFORMANCE NOTE:
--   All JOINs are on indexed FK columns. PostgreSQL will use nested-loop joins
--   with index lookups. For large datasets (>1M rows), add a covering index
--   if this view is frequently filtered on canonical_title or work_arrangement.
-- =============================================================================

CREATE VIEW public.v_active_jobs AS
SELECT
    -- Job identity
    j.job_id,
    j.source_job_id,
    j.job_title,
    j.canonical_title,

    -- Company dimension
    c.company_name,
    c.industry                                      AS company_industry,
    c.company_size,

    -- Location dimension
    l.city,
    l.state_code,
    l.state_name,
    l.country_code,
    l.country_name,
    l.region,

    -- Employment classification
    et.type_code                                    AS employment_type_code,
    et.type_label                                   AS employment_type,
    el.level_code                                   AS experience_level_code,
    el.level_label                                  AS experience_level,
    el.sort_order                                   AS experience_sort_order,

    -- Work arrangement
    j.is_remote,
    j.work_arrangement,

    -- Content
    j.description,
    j.posting_url,

    -- Lifecycle
    j.posted_date,
    j.expiry_date,
    j.is_active,

    -- Provenance
    ds.source_name                                  AS data_source,
    ds.display_name                                 AS data_source_label,
    j.pipeline_run_id,

    -- Audit
    j.created_at,
    j.updated_at

FROM public.jobs j
LEFT JOIN public.companies c
    ON c.company_id       = j.company_id
LEFT JOIN public.locations l
    ON l.location_id      = j.location_id
LEFT JOIN public.employment_types et
    ON et.employment_type_id = j.employment_type_id
LEFT JOIN public.experience_levels el
    ON el.experience_level_id = j.experience_level_id
JOIN public.data_sources ds
    ON ds.data_source_id  = j.data_source_id
WHERE
    j.is_active = TRUE;

COMMENT ON VIEW public.v_active_jobs IS
    'Denormalised flat view of all active job postings with all dimension attributes joined. '
    'Always returns live data. Used by ETL conflict detection and Power BI detail pages.';


-- =============================================================================
-- REGULAR VIEW 2: v_job_skills_detail
-- =============================================================================
-- PURPOSE:
--   Joins job_skills with skills and v_active_jobs to produce one row per
--   (job, skill) pair with full job and skill context.
--   Used for skill-level analytics that need to know which company or city
--   a skill posting came from.
--
-- WHY REGULAR (NOT MATERIALIZED):
--   The ETL loading layer queries this to check "which skills are already
--   linked to this job?" during incremental upsert. Must be live.
-- =============================================================================

CREATE VIEW public.v_job_skills_detail AS
SELECT
    js.job_skill_id,
    js.job_id,
    js.skill_id,
    js.is_required,
    js.proficiency_level,
    js.extracted_text,

    -- Skill attributes
    s.skill_name,
    s.skill_category,
    s.aliases                                       AS skill_aliases,

    -- Job attributes (from v_active_jobs)
    aj.job_title,
    aj.canonical_title,
    aj.company_name,
    aj.company_industry,
    aj.city,
    aj.state_code,
    aj.country_code,
    aj.experience_level,
    aj.employment_type,
    aj.work_arrangement,
    aj.is_remote,
    aj.posted_date,
    aj.data_source

FROM public.job_skills js
JOIN public.skills s
    ON s.skill_id  = js.skill_id
JOIN public.v_active_jobs aj
    ON aj.job_id   = js.job_id;

COMMENT ON VIEW public.v_job_skills_detail IS
    'One row per (active job, skill) pair with full job and skill context. '
    'Used for skill-segmented analytics and ETL skill reconciliation.';


-- =============================================================================
-- REGULAR VIEW 3: v_pipeline_health
-- =============================================================================
-- PURPOSE:
--   Operational monitoring view showing the last N pipeline runs per source.
--   Used by the ops dashboard to quickly identify stuck or failed pipelines.
--
-- WHY REGULAR (NOT MATERIALIZED):
--   Pipeline run data changes every time a run executes. A materialized view
--   refreshed hourly would miss runs that completed in the last hour.
--   Regular view = always live = correct for monitoring.
-- =============================================================================

CREATE VIEW public.v_pipeline_health AS
WITH ranked_runs AS (
    SELECT
        pr.*,
        ds.source_name,
        ds.display_name,
        -- Rank runs per source by start time (latest = rank 1)
        ROW_NUMBER() OVER (
            PARTITION BY pr.data_source_id
            ORDER BY pr.started_at DESC
        )                                                               AS run_rank,
        -- Is this run taking suspiciously long? (>2 hours = potential hang)
        CASE
            WHEN pr.status = 'RUNNING'
                AND NOW() - pr.started_at > INTERVAL '2 hours'
            THEN TRUE
            ELSE FALSE
        END                                                             AS is_potentially_hung,
        -- Time since last successful run for this source
        MAX(pr.completed_at) FILTER (WHERE pr.status = 'SUCCESS')
            OVER (PARTITION BY pr.data_source_id)                      AS last_success_time
    FROM public.pipeline_runs pr
    JOIN public.data_sources ds
        ON ds.data_source_id = pr.data_source_id
)
SELECT
    run_id,
    source_name,
    display_name,
    status,
    started_at,
    completed_at,
    duration_seconds,
    rows_extracted,
    rows_transformed,
    rows_loaded,
    rows_rejected,
    CASE
        WHEN rows_extracted > 0
        THEN ROUND(rows_rejected * 100.0 / rows_extracted, 2)
        ELSE NULL
    END                                                                 AS rejection_rate_pct,
    is_potentially_hung,
    last_success_time,
    NOW() - last_success_time                                           AS time_since_last_success,
    error_message,
    pipeline_version,
    run_rank
FROM ranked_runs
WHERE
    run_rank <= 5   -- Last 5 runs per source
ORDER BY
    source_name,
    started_at DESC;

COMMENT ON VIEW public.v_pipeline_health IS
    'Operational monitoring view: last 5 pipeline runs per source. '
    'Flags hung runs (>2 hours in RUNNING state). Always live data.';


-- =============================================================================
-- MATERIALIZED VIEW 1: mv_company_stats
-- =============================================================================
-- PURPOSE:
--   Pre-aggregated company-level metrics for Power BI "Top Hiring Companies" visual.
--   Avoids a 3-table JOIN + 2 aggregations on every dashboard refresh.
--
-- REFRESH STRATEGY:
--   After each successful pipeline run (in the orchestrator's post-load step).
--   Use CONCURRENTLY to avoid blocking Power BI readers.
--   Requires a UNIQUE index on the materialized view (created below).
--
-- WHY MATERIALIZED:
--   The underlying query joins jobs (millions of rows), salary_ranges, and
--   companies. Pre-computing it takes ~3 seconds at load time but makes
--   Power BI refreshes sub-100ms.
-- =============================================================================

CREATE MATERIALIZED VIEW public.mv_company_stats AS
SELECT
    c.company_id,
    c.company_name,
    c.industry,
    c.company_size,

    -- Posting volume metrics
    COUNT(DISTINCT j.job_id)                                            AS total_active_postings,
    COUNT(DISTINCT j.job_id) FILTER (WHERE j.is_remote = TRUE)         AS remote_postings,
    COUNT(DISTINCT j.job_id) FILTER (WHERE j.work_arrangement = 'HYBRID') AS hybrid_postings,
    ROUND(
        COUNT(DISTINCT j.job_id) FILTER (WHERE j.is_remote = TRUE) * 100.0
        / NULLIF(COUNT(DISTINCT j.job_id), 0),
        1
    )                                                                   AS remote_pct,

    -- Temporal range
    MIN(j.posted_date)                                                  AS first_posted,
    MAX(j.posted_date)                                                  AS last_posted,

    -- Experience profile (most common level for this company)
    MODE() WITHIN GROUP (ORDER BY el.level_code)                        AS dominant_experience_level,

    -- Salary statistics
    ROUND(AVG(sr.salary_midpoint), 0)                                   AS avg_salary,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sr.salary_midpoint),
        0
    )                                                                   AS median_salary,

    -- Demand rank (dense rank by posting count)
    DENSE_RANK() OVER (ORDER BY COUNT(DISTINCT j.job_id) DESC)         AS posting_rank,

    -- Metadata
    NOW()                                                               AS refreshed_at

FROM public.jobs j
JOIN public.companies c
    ON c.company_id = j.company_id
LEFT JOIN public.experience_levels el
    ON el.experience_level_id = j.experience_level_id
LEFT JOIN public.salary_ranges sr
    ON sr.job_id       = j.job_id
    AND sr.currency_code = 'USD'
    AND sr.salary_period = 'ANNUAL'
    AND sr.salary_midpoint IS NOT NULL
WHERE
    j.is_active = TRUE
GROUP BY
    c.company_id,
    c.company_name,
    c.industry,
    c.company_size
WITH DATA;

-- UNIQUE index required for REFRESH CONCURRENTLY (PostgreSQL requirement)
CREATE UNIQUE INDEX uix_mv_company_stats_company_id
    ON public.mv_company_stats (company_id);

-- Supports sorting/filtering by rank in Power BI
CREATE INDEX ix_mv_company_stats_posting_rank
    ON public.mv_company_stats (posting_rank);

COMMENT ON MATERIALIZED VIEW public.mv_company_stats IS
    'Pre-aggregated company hiring metrics. Refresh after each pipeline run. '
    'Backing view for Power BI "Top Hiring Companies" visual.';


-- =============================================================================
-- MATERIALIZED VIEW 2: mv_skill_demand
-- =============================================================================
-- PURPOSE:
--   Pre-aggregated skill demand metrics. The "Most In-Demand Skills" visual
--   in Power BI queries this instead of the raw job_skills + jobs + skills JOIN.
--
-- REFRESH STRATEGY: After each pipeline run (same as mv_company_stats).
-- =============================================================================

CREATE MATERIALIZED VIEW public.mv_skill_demand AS
SELECT
    s.skill_id,
    s.skill_name,
    s.skill_category,

    -- Job demand
    COUNT(DISTINCT js.job_id)                                           AS total_job_count,
    COUNT(DISTINCT js.job_id) FILTER (WHERE js.is_required = TRUE)     AS required_job_count,
    COUNT(DISTINCT j.company_id)                                        AS hiring_company_count,
    COUNT(DISTINCT js.job_id) FILTER (WHERE j.is_remote = TRUE)        AS remote_job_count,

    -- Demand percentages
    ROUND(
        COUNT(DISTINCT js.job_id) * 100.0
        / NULLIF((SELECT COUNT(*) FROM public.jobs WHERE is_active = TRUE), 0),
        2
    )                                                                   AS pct_of_all_jobs,
    ROUND(
        COUNT(DISTINCT js.job_id) FILTER (WHERE js.is_required = TRUE) * 100.0
        / NULLIF(COUNT(DISTINCT js.job_id), 0),
        1
    )                                                                   AS required_pct,

    -- Salary context
    ROUND(AVG(sr.salary_midpoint), 0)                                   AS avg_salary,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sr.salary_midpoint),
        0
    )                                                                   AS median_salary,

    -- Trend (last 30 days vs prior 30 days)
    COUNT(js.job_id) FILTER (
        WHERE j.posted_date >= CURRENT_DATE - INTERVAL '30 days'
    )                                                                   AS last_30d_mentions,
    COUNT(js.job_id) FILTER (
        WHERE j.posted_date >= CURRENT_DATE - INTERVAL '60 days'
            AND j.posted_date < CURRENT_DATE - INTERVAL '30 days'
    )                                                                   AS prior_30d_mentions,

    -- Ranks
    DENSE_RANK() OVER (ORDER BY COUNT(DISTINCT js.job_id) DESC)        AS global_rank,
    DENSE_RANK() OVER (
        PARTITION BY s.skill_category
        ORDER BY COUNT(DISTINCT js.job_id) DESC
    )                                                                   AS category_rank,

    -- Metadata
    NOW()                                                               AS refreshed_at

FROM public.job_skills js
JOIN public.jobs j
    ON j.job_id   = js.job_id
    AND j.is_active = TRUE
JOIN public.skills s
    ON s.skill_id = js.skill_id
    AND s.is_active = TRUE
LEFT JOIN public.salary_ranges sr
    ON sr.job_id       = js.job_id
    AND sr.currency_code = 'USD'
    AND sr.salary_period = 'ANNUAL'
    AND sr.salary_midpoint IS NOT NULL
GROUP BY
    s.skill_id,
    s.skill_name,
    s.skill_category
WITH DATA;

CREATE UNIQUE INDEX uix_mv_skill_demand_skill_id
    ON public.mv_skill_demand (skill_id);

CREATE INDEX ix_mv_skill_demand_global_rank
    ON public.mv_skill_demand (global_rank);

CREATE INDEX ix_mv_skill_demand_category_rank
    ON public.mv_skill_demand (skill_category, category_rank);

COMMENT ON MATERIALIZED VIEW public.mv_skill_demand IS
    'Pre-aggregated skill demand metrics with salary context. '
    'Backing view for Power BI "Top Skills" and "Skills vs Salary" visuals.';


-- =============================================================================
-- MATERIALIZED VIEW 3: mv_monthly_hiring_trend
-- =============================================================================
-- PURPOSE:
--   Monthly time-series of job postings with MoM growth rate pre-computed.
--   Power BI line charts use this for the "Hiring Trends Over Time" visual.
--
-- WHY MATERIALIZED:
--   DATE_TRUNC + window function LAG over a large jobs table is expensive.
--   Pre-computing the monthly series (typically 24–36 rows of output)
--   makes time-series chart rendering instant.
-- =============================================================================

CREATE MATERIALIZED VIEW public.mv_monthly_hiring_trend AS
WITH monthly_raw AS (
    SELECT
        DATE_TRUNC('month', j.posted_date)::DATE                        AS posting_month,
        COUNT(j.job_id)                                                 AS total_jobs,
        COUNT(j.job_id) FILTER (WHERE j.work_arrangement = 'REMOTE')   AS remote_jobs,
        COUNT(j.job_id) FILTER (WHERE j.work_arrangement = 'HYBRID')   AS hybrid_jobs,
        COUNT(j.job_id) FILTER (WHERE j.work_arrangement = 'ON_SITE')  AS onsite_jobs,
        COUNT(DISTINCT j.company_id)                                    AS unique_companies,
        COUNT(DISTINCT j.canonical_title)                               AS unique_titles,
        ROUND(AVG(sr.salary_midpoint), 0)                              AS avg_salary
    FROM public.jobs j
    LEFT JOIN public.salary_ranges sr
        ON sr.job_id       = j.job_id
        AND sr.currency_code = 'USD'
        AND sr.salary_period = 'ANNUAL'
    WHERE
        j.posted_date IS NOT NULL
    GROUP BY DATE_TRUNC('month', j.posted_date)
)
SELECT
    mr.posting_month,
    mr.total_jobs,
    mr.remote_jobs,
    mr.hybrid_jobs,
    mr.onsite_jobs,
    mr.unique_companies,
    mr.unique_titles,
    mr.avg_salary,
    ROUND(mr.remote_jobs * 100.0 / NULLIF(mr.total_jobs, 0), 1)        AS remote_pct,
    LAG(mr.total_jobs, 1) OVER (ORDER BY mr.posting_month)             AS prev_month_jobs,
    ROUND(
        (mr.total_jobs - LAG(mr.total_jobs, 1) OVER (ORDER BY mr.posting_month))
        * 100.0
        / NULLIF(LAG(mr.total_jobs, 1) OVER (ORDER BY mr.posting_month), 0),
        2
    )                                                                   AS mom_growth_pct,
    ROUND(
        AVG(mr.total_jobs::NUMERIC) OVER (
            ORDER BY mr.posting_month
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ), 0
    )                                                                   AS rolling_3mo_avg,
    SUM(mr.total_jobs) OVER (ORDER BY mr.posting_month)                AS cumulative_total,
    NOW()                                                               AS refreshed_at
FROM monthly_raw mr
ORDER BY mr.posting_month
WITH DATA;

CREATE UNIQUE INDEX uix_mv_monthly_hiring_trend_month
    ON public.mv_monthly_hiring_trend (posting_month);

COMMENT ON MATERIALIZED VIEW public.mv_monthly_hiring_trend IS
    'Monthly hiring time-series with MoM growth, rolling average, and cumulative total. '
    'Refresh nightly. Backing view for Power BI "Hiring Trends" line chart.';


-- =============================================================================
-- MATERIALIZED VIEW 4: mv_salary_by_city
-- =============================================================================
-- PURPOSE:
--   City-level salary statistics for the "Salary by Location" map visual.
--   Pre-computes expensive PERCENTILE_CONT aggregates.
-- =============================================================================

CREATE MATERIALIZED VIEW public.mv_salary_by_city AS
SELECT
    l.city,
    l.state_code,
    l.state_name,
    l.country_code,
    l.country_name,

    COUNT(DISTINCT j.job_id)                                            AS job_count,
    COUNT(DISTINCT j.company_id)                                        AS company_count,

    ROUND(AVG(sr.salary_midpoint), 0)                                   AS avg_salary,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sr.salary_midpoint),
        0
    )                                                                   AS median_salary,
    ROUND(
        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY sr.salary_midpoint),
        0
    )                                                                   AS p25_salary,
    ROUND(
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY sr.salary_midpoint),
        0
    )                                                                   AS p75_salary,
    ROUND(MIN(sr.salary_min), 0)                                        AS min_salary,
    ROUND(MAX(sr.salary_max), 0)                                        AS max_salary,

    RANK() OVER (
        PARTITION BY l.country_code
        ORDER BY PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sr.salary_midpoint) DESC NULLS LAST
    )                                                                   AS salary_rank_in_country,

    NOW()                                                               AS refreshed_at

FROM public.jobs j
JOIN public.locations l
    ON l.location_id  = j.location_id
JOIN public.salary_ranges sr
    ON sr.job_id       = j.job_id
    AND sr.currency_code = 'USD'
    AND sr.salary_period = 'ANNUAL'
    AND sr.salary_midpoint IS NOT NULL
WHERE
    j.is_active = TRUE
    AND l.city IS NOT NULL
GROUP BY
    l.city,
    l.state_code,
    l.state_name,
    l.country_code,
    l.country_name
HAVING
    COUNT(DISTINCT j.job_id) >= 10
WITH DATA;

CREATE UNIQUE INDEX uix_mv_salary_by_city
    ON public.mv_salary_by_city (city, state_code, country_code);

CREATE INDEX ix_mv_salary_by_city_median
    ON public.mv_salary_by_city (median_salary DESC);

COMMENT ON MATERIALIZED VIEW public.mv_salary_by_city IS
    'Pre-computed salary percentiles per city. Minimum 10 postings per city. '
    'Backing view for Power BI map and "Salary by City" bar chart.';


-- =============================================================================
-- MATERIALIZED VIEW 5: mv_salary_by_skill
-- =============================================================================
-- PURPOSE:
--   Skill salary premium table — which skills pay above market median?
--   The "Salary by Skill" scatter plot in Power BI queries this.
-- =============================================================================

CREATE MATERIALIZED VIEW public.mv_salary_by_skill AS
WITH market_baseline AS (
    SELECT
        ROUND(
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sr.salary_midpoint), 0
        ) AS market_median
    FROM public.salary_ranges sr
    JOIN public.jobs j ON j.job_id = sr.job_id AND j.is_active = TRUE
    WHERE sr.currency_code = 'USD' AND sr.salary_period = 'ANNUAL' AND sr.salary_midpoint IS NOT NULL
)
SELECT
    s.skill_id,
    s.skill_name,
    s.skill_category,

    COUNT(DISTINCT js.job_id)                                           AS job_count,
    ROUND(AVG(sr.salary_midpoint), 0)                                   AS avg_salary,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sr.salary_midpoint), 0
    )                                                                   AS median_salary,
    ROUND(
        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY sr.salary_midpoint), 0
    )                                                                   AS p25_salary,
    ROUND(
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY sr.salary_midpoint), 0
    )                                                                   AS p75_salary,

    mb.market_median,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sr.salary_midpoint)
        - mb.market_median, 0
    )                                                                   AS salary_premium,
    ROUND(
        (PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sr.salary_midpoint)
         - mb.market_median) * 100.0
        / NULLIF(mb.market_median, 0), 2
    )                                                                   AS salary_premium_pct,

    RANK() OVER (ORDER BY
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sr.salary_midpoint)
        DESC NULLS LAST
    )                                                                   AS salary_rank,

    NOW()                                                               AS refreshed_at

FROM public.job_skills js
JOIN public.jobs j
    ON j.job_id   = js.job_id AND j.is_active = TRUE
JOIN public.skills s
    ON s.skill_id = js.skill_id AND s.is_active = TRUE
JOIN public.salary_ranges sr
    ON sr.job_id       = js.job_id
    AND sr.currency_code = 'USD'
    AND sr.salary_period = 'ANNUAL'
    AND sr.salary_midpoint IS NOT NULL
CROSS JOIN market_baseline mb
GROUP BY
    s.skill_id, s.skill_name, s.skill_category, mb.market_median
HAVING
    COUNT(DISTINCT js.job_id) >= 15
WITH DATA;

CREATE UNIQUE INDEX uix_mv_salary_by_skill_skill_id
    ON public.mv_salary_by_skill (skill_id);

CREATE INDEX ix_mv_salary_by_skill_rank
    ON public.mv_salary_by_skill (salary_rank);

COMMENT ON MATERIALIZED VIEW public.mv_salary_by_skill IS
    'Skill salary premiums vs market median. Min 15 postings per skill. '
    'Backing view for Power BI "Average Salary by Skill" scatter chart.';


-- =============================================================================
-- ADDITIONAL PERFORMANCE INDEXES
-- =============================================================================
-- These indexes complement the ones in schema.sql.
-- They are created here (rather than in schema.sql) because they are
-- specific to query patterns identified in analytics.sql — they would
-- not be obvious from the schema definition alone.
-- =============================================================================

-- ── Covering index for the most common BI filter: active jobs by title + date ─
-- Covers: WHERE is_active = TRUE AND canonical_title = ? AND posted_date >= ?
-- A "covering index" includes extra columns so the query can be satisfied
-- from the index alone without accessing the heap (table rows).
-- include() is a PostgreSQL 11+ feature — stores columns in the leaf nodes
-- of the B-tree without including them in the sort key.
CREATE INDEX ix_jobs_active_title_date
    ON public.jobs (canonical_title, posted_date DESC NULLS LAST)
    INCLUDE (company_id, location_id, is_remote, work_arrangement)
    WHERE is_active = TRUE;

COMMENT ON INDEX public.ix_jobs_active_title_date IS
    'Covering index for canonical_title + date filter on active jobs. '
    'Avoids heap access for common BI queries. PostgreSQL 11+ only.';

-- ── Index for salary analytics filtered by currency + period ─────────────────
-- Powers all salary aggregation queries that filter currency='USD' AND period='ANNUAL'.
-- Without this, every salary query scans the entire salary_ranges table.
CREATE INDEX ix_salary_ranges_currency_period_midpoint
    ON public.salary_ranges (currency_code, salary_period, salary_midpoint)
    WHERE salary_midpoint IS NOT NULL;

COMMENT ON INDEX public.ix_salary_ranges_currency_period_midpoint IS
    'Supports salary analytics filtered on USD/ANNUAL with non-null midpoint.';

-- ── Composite index for skill demand queries ──────────────────────────────────
-- Powers: JOIN job_skills WHERE job_id IN (...) AND is_required = TRUE
CREATE INDEX ix_job_skills_job_required
    ON public.job_skills (job_id, is_required, skill_id)
    INCLUDE (proficiency_level);

COMMENT ON INDEX public.ix_job_skills_job_required IS
    'Composite covering index for skill demand aggregations. '
    'Allows skill queries to be resolved from index without heap access.';

-- ── Expression index for case-insensitive company name lookup ─────────────────
-- Powers ETL deduplication: WHERE LOWER(company_name) = LOWER(:name)
-- Without this, every dedup check requires a seqscan or a LIKE with no index.
CREATE INDEX ix_companies_name_lower
    ON public.companies (LOWER(company_name));

COMMENT ON INDEX public.ix_companies_name_lower IS
    'Expression index for case-insensitive company name lookup in ETL deduplication.';

-- ── Expression index for case-insensitive skill name lookup ──────────────────
CREATE INDEX ix_skills_name_lower
    ON public.skills (LOWER(skill_name));

COMMENT ON INDEX public.ix_skills_name_lower IS
    'Expression index for case-insensitive skill name lookup during ETL loading.';


-- =============================================================================
-- VERIFICATION
-- =============================================================================

-- List all views created:
-- SELECT schemaname, viewname, 'regular' AS view_type
-- FROM pg_views WHERE schemaname = 'public'
-- UNION ALL
-- SELECT schemaname, matviewname, 'materialized'
-- FROM pg_matviews WHERE schemaname = 'public'
-- ORDER BY view_type, viewname;

-- Check row counts in materialized views:
-- SELECT 'mv_company_stats' AS view_name,        COUNT(*) FROM public.mv_company_stats
-- UNION ALL SELECT 'mv_skill_demand',             COUNT(*) FROM public.mv_skill_demand
-- UNION ALL SELECT 'mv_monthly_hiring_trend',     COUNT(*) FROM public.mv_monthly_hiring_trend
-- UNION ALL SELECT 'mv_salary_by_city',           COUNT(*) FROM public.mv_salary_by_city
-- UNION ALL SELECT 'mv_salary_by_skill',          COUNT(*) FROM public.mv_salary_by_skill;

-- =============================================================================
-- END OF VIEWS
-- =============================================================================
