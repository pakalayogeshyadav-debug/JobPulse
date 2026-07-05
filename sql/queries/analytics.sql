-- =============================================================================
-- JobPulse Data Engineering Pipeline
-- File        : sql/queries/analytics.sql
-- Purpose     : Production-quality analytical SQL for the JobPulse dashboard
-- Author      : Senior Data Engineer
-- Version     : 1.0.0
-- Database    : PostgreSQL 15+
--
-- Covers:
--   Q1  — Top Hiring Companies
--   Q2  — Top In-Demand Skills
--   Q3  — Highest-Paying Jobs (with salary spread)
--   Q4  — Monthly Hiring Trends
--   Q5  — Remote vs On-Site Job Percentage
--   Q6  — Experience Level Distribution
--   Q7  — Average Salary by City
--   Q8  — Average Salary by Skill
--   Q9  — Most Requested Technologies (by category)
--   Q10 — Salary Percentile Bands by Canonical Title
--
-- Design Principles Applied:
--   • CTEs (WITH) — break complex logic into readable, named steps
--   • Window Functions — rank, percentile, running totals without sub-selects
--   • FILTER clause — conditional aggregation, cleaner than CASE WHEN SUM(...)
--   • Partial indexes already defined in schema.sql are exploited here
--   • All queries filter on is_active = TRUE (hits ix_jobs_is_active_partial)
--   • Date-range params are :start_date / :end_date (replace with BI tool vars)
--   • All monetary math uses salary_midpoint (GENERATED ALWAYS AS stored column)
--     to avoid (min+max)/2 computation on every row at query time
--
-- Usage:
--   psql -d jobpulse_dw -f sql/queries/analytics.sql
--   Or paste individual queries into Power BI / pgAdmin / DBeaver
-- =============================================================================


-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 1: TOP HIRING COMPANIES
-- ─────────────────────────────────────────────────────────────────────────────
-- WHAT   : Ranks companies by total active job posting count.
-- WHY    : "Top Hiring Companies" is a core Power BI visual.
--          Recruiter and job-seeker dashboards both need this.
-- HOW    :
--   Step 1 (company_posting_counts CTE):
--     Aggregate job_id count per company. Also compute remote_count using
--     FILTER — a cleaner alternative to SUM(CASE WHEN is_remote THEN 1 ELSE 0 END).
--
--   Step 2 (ranked CTE):
--     Apply DENSE_RANK() over posting_count DESC.
--     DENSE_RANK vs RANK: ties share the same rank, and the next rank is
--     the same number + 1 (not a skip). This matters for Power BI rank visuals.
--
--   Step 3 (final SELECT):
--     Add avg_salary_midpoint from salary_ranges via an outer join so companies
--     without salary data still appear in the results.
--
-- INDEXES USED:
--   ix_jobs_company_id      (FK join from jobs → companies)
--   ix_jobs_is_active_partial (WHERE is_active = TRUE)
--   ix_salary_ranges_job_id   (join salary_ranges → jobs)
-- ─────────────────────────────────────────────────────────────────────────────

WITH company_posting_counts AS (
    SELECT
        j.company_id,
        COUNT(j.job_id)                                          AS total_postings,
        COUNT(j.job_id) FILTER (WHERE j.is_remote = TRUE)       AS remote_postings,
        COUNT(j.job_id) FILTER (WHERE j.is_remote = FALSE)      AS onsite_postings,
        COUNT(j.job_id) FILTER (WHERE j.work_arrangement = 'HYBRID') AS hybrid_postings,
        MIN(j.posted_date)                                       AS earliest_posting,
        MAX(j.posted_date)                                       AS latest_posting
    FROM public.jobs j
    WHERE
        j.is_active    = TRUE
        AND j.company_id IS NOT NULL
        -- Parameterised date window (replace with BI tool variable or hardcode)
        AND j.posted_date >= COALESCE(:start_date, '2020-01-01'::DATE)
        AND j.posted_date <= COALESCE(:end_date,   CURRENT_DATE)
    GROUP BY j.company_id
),
company_salaries AS (
    -- Compute per-company salary stats in a separate CTE to keep logic clean
    -- Uses salary_midpoint (the stored generated column) — no arithmetic at runtime
    SELECT
        j.company_id,
        ROUND(AVG(sr.salary_midpoint), 0)                       AS avg_salary,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY sr.salary_midpoint
        ), 0)                                                    AS median_salary,
        ROUND(MIN(sr.salary_min), 0)                            AS min_salary,
        ROUND(MAX(sr.salary_max), 0)                            AS max_salary
    FROM public.salary_ranges sr
    JOIN public.jobs j
        ON j.job_id = sr.job_id
    WHERE
        sr.currency_code  = 'USD'
        AND sr.salary_period  = 'ANNUAL'
        AND sr.salary_midpoint IS NOT NULL
    GROUP BY j.company_id
),
ranked AS (
    SELECT
        cpc.*,
        cs.avg_salary,
        cs.median_salary,
        cs.min_salary,
        cs.max_salary,
        DENSE_RANK() OVER (ORDER BY cpc.total_postings DESC)    AS posting_rank,
        -- Running total as a window to compute what % of all postings
        -- this company accounts for
        ROUND(
            cpc.total_postings * 100.0
            / SUM(cpc.total_postings) OVER (),
            2
        )                                                        AS pct_of_all_postings
    FROM company_posting_counts cpc
    LEFT JOIN company_salaries cs
        ON cs.company_id = cpc.company_id
)
SELECT
    r.posting_rank,
    c.company_name,
    c.industry,
    c.company_size,
    r.total_postings,
    r.remote_postings,
    r.onsite_postings,
    r.hybrid_postings,
    ROUND(r.remote_postings * 100.0 / NULLIF(r.total_postings, 0), 1) AS remote_pct,
    r.pct_of_all_postings,
    r.avg_salary,
    r.median_salary,
    r.earliest_posting,
    r.latest_posting
FROM ranked r
JOIN public.companies c
    ON c.company_id = r.company_id
WHERE
    r.posting_rank <= COALESCE(:top_n, 25)   -- Default: top 25 companies
ORDER BY
    r.posting_rank,
    c.company_name;


-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 2: TOP IN-DEMAND SKILLS
-- ─────────────────────────────────────────────────────────────────────────────
-- WHAT   : Ranks skills by how many distinct active job postings require them.
-- WHY    : The #1 Power BI visual for job seekers — "What skills should I learn?"
-- HOW    :
--   Step 1 (skill_job_counts CTE):
--     COUNT(DISTINCT j.job_id) per skill_id.
--     DISTINCT is critical: one job can link to the same skill twice if the
--     ETL had a bug. DISTINCT gives accurate reach (how many unique jobs need it).
--
--   Step 2 (required_counts CTE):
--     Same aggregation but FILTER (WHERE js.is_required = TRUE).
--     This tells us: of all postings mentioning Python, how many actually REQUIRE it
--     vs just list it as "nice to have"?
--     Uses ix_job_skills_required_skill_id (partial index, smaller/faster).
--
--   Step 3:
--     ROW_NUMBER() for clean sequential ranking.
--     LAG() window function to compute month-over-month rank change (trend).
--     Note: trend requires at least 2 months of data; handled by COALESCE.
--
-- INDEXES USED:
--   ix_job_skills_skill_id          (GROUP BY skill_id)
--   ix_job_skills_required_skill_id (FILTER is_required = TRUE)
--   ix_jobs_is_active_partial       (WHERE is_active = TRUE)
-- ─────────────────────────────────────────────────────────────────────────────

WITH skill_job_counts AS (
    SELECT
        js.skill_id,
        COUNT(DISTINCT js.job_id)                                      AS total_job_count,
        COUNT(DISTINCT js.job_id) FILTER (WHERE js.is_required = TRUE) AS required_job_count,
        COUNT(DISTINCT js.job_id) FILTER (WHERE j.is_remote   = TRUE)  AS remote_job_count,
        COUNT(DISTINCT j.company_id)                                   AS hiring_company_count,
        -- Average salary for jobs requiring this skill
        ROUND(AVG(sr.salary_midpoint), 0)                              AS avg_salary_for_skill
    FROM public.job_skills js
    JOIN public.jobs j
        ON j.job_id = js.job_id
        AND j.is_active = TRUE
        AND j.posted_date >= COALESCE(:start_date, CURRENT_DATE - INTERVAL '12 months')
    LEFT JOIN public.salary_ranges sr
        ON sr.job_id = js.job_id
        AND sr.currency_code  = 'USD'
        AND sr.salary_period  = 'ANNUAL'
    GROUP BY js.skill_id
),
ranked_skills AS (
    SELECT
        sjc.*,
        s.skill_name,
        s.skill_category,
        -- Dense rank by total demand
        DENSE_RANK() OVER (ORDER BY sjc.total_job_count DESC)          AS overall_rank,
        -- Rank within each skill category (for category-filtered visuals)
        DENSE_RANK() OVER (
            PARTITION BY s.skill_category
            ORDER BY sjc.total_job_count DESC
        )                                                               AS category_rank,
        -- Percentage of active jobs that mention this skill
        ROUND(
            sjc.total_job_count * 100.0 / NULLIF(
                (SELECT COUNT(*) FROM public.jobs WHERE is_active = TRUE), 0
            ), 2
        )                                                               AS pct_of_all_jobs,
        -- Required-to-mentioned ratio (high ratio = skill is truly critical)
        ROUND(
            sjc.required_job_count * 100.0 / NULLIF(sjc.total_job_count, 0),
            1
        )                                                               AS required_ratio_pct
    FROM skill_job_counts sjc
    JOIN public.skills s
        ON s.skill_id = sjc.skill_id
        AND s.is_active = TRUE
)
SELECT
    overall_rank,
    skill_name,
    skill_category,
    total_job_count,
    required_job_count,
    required_ratio_pct,
    remote_job_count,
    hiring_company_count,
    avg_salary_for_skill,
    pct_of_all_jobs,
    category_rank
FROM ranked_skills
WHERE
    overall_rank <= COALESCE(:top_n, 30)
ORDER BY
    overall_rank;


-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 3: HIGHEST-PAYING JOBS (WITH SALARY SPREAD)
-- ─────────────────────────────────────────────────────────────────────────────
-- WHAT   : Lists the highest-paying active job postings with full salary context.
-- WHY    : Job seekers want to know which specific postings pay the most.
--          Employers want to benchmark their comp packages vs market.
-- HOW    :
--   salary_spread = salary_max - salary_min.
--   A very wide spread (e.g., $60k–$200k) signals low confidence in the
--   salary data or a deliberately vague posting. We flag these.
--
--   ntile(4) creates salary quartile bands (Q1=lowest 25%, Q4=highest 25%).
--   This lets Power BI show salary distribution without a separate query.
--
--   We ORDER BY salary_midpoint DESC (not salary_max DESC) because:
--   ordering by max creates misleading rankings where "$50k–$300k" beats
--   "$140k–$180k", even though the second is clearly a higher-paying role.
-- ─────────────────────────────────────────────────────────────────────────────

WITH salary_enriched AS (
    SELECT
        j.job_id,
        j.job_title,
        j.canonical_title,
        j.is_remote,
        j.work_arrangement,
        j.posted_date,
        j.posting_url,
        c.company_name,
        c.industry                                                       AS company_industry,
        c.company_size,
        l.city,
        l.state_code,
        l.country_code,
        el.level_label                                                   AS experience_level,
        et.type_label                                                    AS employment_type,
        sr.salary_min,
        sr.salary_max,
        sr.salary_midpoint,
        sr.currency_code,
        sr.salary_period,
        sr.is_estimated,
        -- Salary spread as an absolute value and as a % of midpoint
        (sr.salary_max - sr.salary_min)                                  AS salary_spread,
        ROUND(
            (sr.salary_max - sr.salary_min) * 100.0
            / NULLIF(sr.salary_midpoint, 0),
            1
        )                                                                AS salary_spread_pct,
        -- Flag wide-spread salaries (spread > 60% of midpoint) for data quality
        CASE
            WHEN (sr.salary_max - sr.salary_min) / NULLIF(sr.salary_midpoint, 0) > 0.6
            THEN TRUE
            ELSE FALSE
        END                                                              AS is_wide_spread,
        -- Salary quartile band across entire result set
        NTILE(4) OVER (ORDER BY sr.salary_midpoint ASC NULLS LAST)      AS salary_quartile,
        -- Percentile rank (0.0 – 1.0) — useful for Power BI salary gauge visuals
        PERCENT_RANK() OVER (ORDER BY sr.salary_midpoint ASC NULLS LAST) AS salary_percentile_rank
    FROM public.jobs j
    JOIN public.salary_ranges sr
        ON sr.job_id       = j.job_id
        AND sr.currency_code = 'USD'
        AND sr.salary_period = 'ANNUAL'
        AND sr.salary_midpoint IS NOT NULL
    LEFT JOIN public.companies c
        ON c.company_id = j.company_id
    LEFT JOIN public.locations l
        ON l.location_id = j.location_id
    LEFT JOIN public.experience_levels el
        ON el.experience_level_id = j.experience_level_id
    LEFT JOIN public.employment_types et
        ON et.employment_type_id = j.employment_type_id
    WHERE
        j.is_active   = TRUE
        AND j.posted_date >= COALESCE(:start_date, CURRENT_DATE - INTERVAL '6 months')
)
SELECT
    job_id,
    job_title,
    canonical_title,
    company_name,
    company_industry,
    company_size,
    city,
    state_code,
    country_code,
    experience_level,
    employment_type,
    work_arrangement,
    salary_min,
    salary_max,
    salary_midpoint,
    currency_code,
    salary_spread,
    salary_spread_pct,
    is_wide_spread,
    salary_quartile,
    ROUND(salary_percentile_rank * 100, 1)                               AS salary_percentile_pct,
    is_estimated,
    posted_date,
    posting_url
FROM salary_enriched
ORDER BY
    salary_midpoint DESC NULLS LAST
LIMIT COALESCE(:top_n, 50);


-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 4: MONTHLY HIRING TRENDS
-- ─────────────────────────────────────────────────────────────────────────────
-- WHAT   : Active job count per month, segmented by work arrangement.
--          Also computes MoM growth rate and a 3-month rolling average.
-- WHY    : "Hiring trends over time" is the most-used time-series visual in BI.
--          Growth rate lets analysts see whether hiring is accelerating/decelerating.
--          Rolling average smooths out noise from weekly data upload cycles.
-- HOW    :
--   DATE_TRUNC('month', posted_date) groups all postings in a calendar month.
--   This is better than EXTRACT(YEAR/MONTH) because it produces a single
--   sortable timestamp value instead of two separate integer columns.
--
--   LAG(total_jobs, 1) OVER (ORDER BY month) gives the previous month's count
--   in a single pass — no self-join required.
--
--   AVG() OVER (ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) is a 3-row window
--   = 3-month rolling average. ROWS mode is used (not RANGE) because we have
--   one row per month, so ROWS BETWEEN 2 PRECEDING is exactly 3 months.
-- ─────────────────────────────────────────────────────────────────────────────

WITH monthly_base AS (
    SELECT
        DATE_TRUNC('month', j.posted_date)::DATE                         AS posting_month,
        COUNT(j.job_id)                                                  AS total_jobs,
        COUNT(j.job_id) FILTER (WHERE j.work_arrangement = 'REMOTE')    AS remote_jobs,
        COUNT(j.job_id) FILTER (WHERE j.work_arrangement = 'HYBRID')    AS hybrid_jobs,
        COUNT(j.job_id) FILTER (WHERE j.work_arrangement = 'ON_SITE')   AS onsite_jobs,
        COUNT(j.job_id) FILTER (WHERE j.work_arrangement = 'UNSPECIFIED') AS unspecified_jobs,
        COUNT(DISTINCT j.company_id)                                     AS unique_hiring_companies,
        COUNT(DISTINCT j.canonical_title)                                AS unique_titles_posted,
        -- Average midpoint salary for that month
        ROUND(AVG(sr.salary_midpoint), 0)                                AS avg_monthly_salary
    FROM public.jobs j
    LEFT JOIN public.salary_ranges sr
        ON sr.job_id = j.job_id
        AND sr.currency_code = 'USD'
        AND sr.salary_period = 'ANNUAL'
    WHERE
        j.posted_date IS NOT NULL
        AND j.posted_date >= COALESCE(:start_date, CURRENT_DATE - INTERVAL '24 months')
        AND j.posted_date <= COALESCE(:end_date, CURRENT_DATE)
    GROUP BY DATE_TRUNC('month', j.posted_date)
),
with_growth AS (
    SELECT
        mb.*,
        -- Previous month total for MoM calculation
        LAG(mb.total_jobs, 1) OVER (ORDER BY mb.posting_month)          AS prev_month_jobs,
        -- Month-over-month growth rate (%)
        ROUND(
            (mb.total_jobs - LAG(mb.total_jobs, 1) OVER (ORDER BY mb.posting_month))
            * 100.0
            / NULLIF(LAG(mb.total_jobs, 1) OVER (ORDER BY mb.posting_month), 0),
            2
        )                                                                AS mom_growth_pct,
        -- 3-month rolling average (smooths weekly upload noise)
        ROUND(
            AVG(mb.total_jobs::NUMERIC) OVER (
                ORDER BY mb.posting_month
                ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
            ),
            0
        )                                                                AS rolling_3mo_avg,
        -- Cumulative total (running sum) for "total postings over time" area chart
        SUM(mb.total_jobs) OVER (ORDER BY mb.posting_month)             AS cumulative_total,
        -- Remote percentage for that month
        ROUND(
            mb.remote_jobs * 100.0 / NULLIF(mb.total_jobs, 0),
            1
        )                                                                AS remote_pct
    FROM monthly_base mb
)
SELECT
    posting_month,
    total_jobs,
    remote_jobs,
    hybrid_jobs,
    onsite_jobs,
    unspecified_jobs,
    remote_pct,
    unique_hiring_companies,
    unique_titles_posted,
    avg_monthly_salary,
    prev_month_jobs,
    mom_growth_pct,
    rolling_3mo_avg,
    cumulative_total
FROM with_growth
ORDER BY
    posting_month ASC;


-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 5: REMOTE VS ON-SITE JOB PERCENTAGE
-- ─────────────────────────────────────────────────────────────────────────────
-- WHAT   : Overall breakdown of work arrangement across all active postings,
--          split by canonical title and time period.
-- WHY    : "Remote adoption by role" — a key insight for the dashboard.
--          A Data Scientist may be 70% remote while a Warehouse Manager is 5%.
--          This shows the structural remote-work landscape, not just a headline %.
-- HOW    :
--   GROUPING SETS is the key technique here.
--   GROUPING SETS ((canonical_title, work_arrangement), (work_arrangement), ())
--   produces three aggregation levels in one query pass:
--     • Row per (canonical_title, work_arrangement) — detailed breakdown
--     • Row per work_arrangement (subtotal) — arrangement-level totals
--     • One grand total row (the empty grouping set)
--   This eliminates three separate queries and three UNION ALLs.
--
--   GROUPING(canonical_title) returns 1 when canonical_title is a subtotal
--   row — useful for conditional formatting in Power BI.
-- ─────────────────────────────────────────────────────────────────────────────

WITH arrangement_counts AS (
    SELECT
        COALESCE(j.canonical_title, 'Other / Unclassified')              AS canonical_title,
        j.work_arrangement,
        COUNT(j.job_id)                                                  AS job_count
    FROM public.jobs j
    WHERE
        j.is_active   = TRUE
        AND j.posted_date >= COALESCE(:start_date, CURRENT_DATE - INTERVAL '12 months')
    GROUP BY
        GROUPING SETS (
            (j.canonical_title, j.work_arrangement),   -- Detail rows
            (j.work_arrangement),                       -- Arrangement subtotal
            ()                                          -- Grand total
        )
)
SELECT
    COALESCE(canonical_title, '★ ALL TITLES')                            AS canonical_title,
    COALESCE(work_arrangement, '★ ALL ARRANGEMENTS')                     AS work_arrangement,
    job_count,
    -- Percentage within this canonical_title group
    ROUND(
        job_count * 100.0
        / NULLIF(
            SUM(job_count) FILTER (WHERE work_arrangement IS NOT NULL)
                OVER (PARTITION BY canonical_title),
            0
        ),
        2
    )                                                                    AS pct_within_title,
    -- Overall percentage across everything
    ROUND(
        job_count * 100.0
        / NULLIF(SUM(job_count) OVER (), 0),
        2
    )                                                                    AS pct_of_all,
    -- Flag subtotal rows for conditional formatting in Power BI
    CASE WHEN canonical_title IS NULL THEN TRUE ELSE FALSE END           AS is_arrangement_subtotal,
    CASE WHEN work_arrangement IS NULL THEN TRUE ELSE FALSE END          AS is_grand_total
FROM arrangement_counts
ORDER BY
    canonical_title NULLS LAST,
    job_count DESC;


-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 6: EXPERIENCE LEVEL DISTRIBUTION
-- ─────────────────────────────────────────────────────────────────────────────
-- WHAT   : How many jobs are posted at each experience level (ENTRY → EXECUTIVE)?
--          Cross-tabulated by canonical title and work arrangement.
-- WHY    : Employers use this to see where hiring demand concentrates.
--          Job seekers see at what level each role is predominantly hired.
-- HOW    :
--   el.sort_order from the experience_levels table gives a natural display order
--   (1=Entry, 2=Mid, ... 5=Executive). Always use this for ORDER BY in visuals
--   instead of ORDER BY level_label ASC (which would put "Executive" before "Mid").
--
--   RATIO_TO_REPORT is not available in PostgreSQL — we use the window form of
--   SUM(count) OVER (PARTITION BY ...) to compute the percentage within each
--   canonical_title partition in one pass.
-- ─────────────────────────────────────────────────────────────────────────────

WITH level_counts AS (
    SELECT
        COALESCE(j.canonical_title, 'Other / Unclassified')              AS canonical_title,
        el.level_code,
        el.level_label,
        el.sort_order,
        el.min_years_experience,
        el.max_years_experience,
        COUNT(j.job_id)                                                  AS job_count,
        COUNT(j.job_id) FILTER (WHERE j.is_remote = TRUE)               AS remote_count,
        ROUND(AVG(sr.salary_midpoint), 0)                               AS avg_salary
    FROM public.jobs j
    JOIN public.experience_levels el
        ON el.experience_level_id = j.experience_level_id
    LEFT JOIN public.salary_ranges sr
        ON sr.job_id       = j.job_id
        AND sr.currency_code = 'USD'
        AND sr.salary_period = 'ANNUAL'
    WHERE
        j.is_active   = TRUE
        AND j.posted_date >= COALESCE(:start_date, CURRENT_DATE - INTERVAL '12 months')
    GROUP BY
        j.canonical_title,
        el.level_code,
        el.level_label,
        el.sort_order,
        el.min_years_experience,
        el.max_years_experience
)
SELECT
    canonical_title,
    level_code,
    level_label,
    sort_order,
    COALESCE(min_years_experience::TEXT, '?')
        || '–'
        || COALESCE(max_years_experience::TEXT, '+')
        || ' yrs'                                                        AS experience_range,
    job_count,
    remote_count,
    ROUND(remote_count * 100.0 / NULLIF(job_count, 0), 1)               AS remote_pct,
    avg_salary,
    -- % of all jobs for this canonical title
    ROUND(
        job_count * 100.0
        / NULLIF(SUM(job_count) OVER (PARTITION BY canonical_title), 0),
        2
    )                                                                    AS pct_within_title,
    -- % of all jobs across all titles
    ROUND(
        job_count * 100.0
        / NULLIF(SUM(job_count) OVER (), 0),
        2
    )                                                                    AS pct_of_all
FROM level_counts
ORDER BY
    canonical_title,
    sort_order ASC;


-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 7: AVERAGE SALARY BY CITY
-- ─────────────────────────────────────────────────────────────────────────────
-- WHAT   : Average, median, and salary spread by city (USD, ANNUAL only).
--          Ranked by median salary descending.
-- WHY    : "Salary by location" directly answers the most popular job seeker
--          question: "Should I move to San Francisco or stay in Austin?"
-- HOW    :
--   We use PERCENTILE_CONT(0.5) for median rather than AVG because salaries
--   are right-skewed — a handful of $500k+ executive postings can inflate the
--   mean significantly. Median gives a more truthful central tendency.
--
--   PERCENTILE_CONT is an ordered-set aggregate function — it takes an
--   ORDER BY clause inside the function call, not in the outer query.
--   It interpolates between the two middle values for even-count datasets.
--   PERCENTILE_DISC would return an actual data point (no interpolation).
--   We use CONT for smoother results.
--
--   Minimum posting count filter (HAVING COUNT >= 10) removes cities with
--   1-2 extreme outlier postings that would dominate the ranking.
-- ─────────────────────────────────────────────────────────────────────────────

WITH city_salary_stats AS (
    SELECT
        l.city,
        l.state_code,
        l.country_code,
        COUNT(DISTINCT j.job_id)                                         AS job_count,
        COUNT(DISTINCT j.company_id)                                     AS company_count,
        ROUND(AVG(sr.salary_midpoint), 0)                               AS avg_salary,
        ROUND(
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sr.salary_midpoint),
            0
        )                                                                AS median_salary,
        ROUND(
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY sr.salary_midpoint),
            0
        )                                                                AS p25_salary,
        ROUND(
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY sr.salary_midpoint),
            0
        )                                                                AS p75_salary,
        ROUND(MIN(sr.salary_min), 0)                                    AS floor_salary,
        ROUND(MAX(sr.salary_max), 0)                                    AS ceiling_salary,
        -- Interquartile range — a spread metric robust to outliers
        ROUND(
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY sr.salary_midpoint)
            - PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY sr.salary_midpoint),
            0
        )                                                                AS iqr_salary
    FROM public.jobs j
    JOIN public.locations l
        ON l.location_id = j.location_id
    JOIN public.salary_ranges sr
        ON sr.job_id       = j.job_id
        AND sr.currency_code = 'USD'
        AND sr.salary_period = 'ANNUAL'
        AND sr.salary_midpoint IS NOT NULL
    WHERE
        j.is_active   = TRUE
        AND l.city    IS NOT NULL
        AND j.posted_date >= COALESCE(:start_date, CURRENT_DATE - INTERVAL '12 months')
    GROUP BY
        l.city,
        l.state_code,
        l.country_code
    HAVING
        -- Filter out cities with too few postings to produce stable statistics
        COUNT(DISTINCT j.job_id) >= COALESCE(:min_postings, 10)
)
SELECT
    city,
    state_code,
    country_code,
    job_count,
    company_count,
    avg_salary,
    median_salary,
    p25_salary,
    p75_salary,
    floor_salary,
    ceiling_salary,
    iqr_salary,
    -- Rank by median salary (most meaningful for city comparison)
    RANK() OVER (ORDER BY median_salary DESC NULLS LAST)                AS salary_rank,
    -- Salary relative to the national median (how many % above/below?)
    ROUND(
        (median_salary - PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY median_salary
        ) OVER ()) * 100.0
        / NULLIF(
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY median_salary) OVER (),
            0
        ),
        2
    )                                                                    AS pct_vs_national_median
FROM city_salary_stats
ORDER BY
    salary_rank
LIMIT COALESCE(:top_n, 30);


-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 8: AVERAGE SALARY BY SKILL
-- ─────────────────────────────────────────────────────────────────────────────
-- WHAT   : Which skills are associated with the highest-paying jobs?
--          Ranked by median salary, with a salary premium calculation.
-- WHY    : Answers the question "What specific skills earn me more money?"
--          This is the most actionable insight for a Data Engineer career path.
-- HOW    :
--   The "salary premium" is computed as:
--     skill_median_salary - overall_median_salary (across all jobs)
--   This is computed using a cross join to a single-row CTE (baseline_salary)
--   that holds the overall median. Cross joining a single row is zero-cost
--   and avoids a correlated subquery per row.
--
--   We use WITHIN GROUP (ORDER BY ...) (ordered-set aggregate) for PERCENTILE_CONT.
--   This cannot be used as a window function — it must be in a GROUP BY context.
--   The window-function version for percentile is PERCENTILE_CONT() OVER (...),
--   which we use in the outer query for overall_median.
-- ─────────────────────────────────────────────────────────────────────────────

WITH baseline_salary AS (
    -- Overall market median — computed once, cross joined below
    SELECT
        ROUND(
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sr.salary_midpoint),
            0
        ) AS overall_median_salary,
        ROUND(AVG(sr.salary_midpoint), 0) AS overall_avg_salary
    FROM public.salary_ranges sr
    JOIN public.jobs j
        ON j.job_id = sr.job_id
        AND j.is_active = TRUE
    WHERE
        sr.currency_code  = 'USD'
        AND sr.salary_period  = 'ANNUAL'
        AND sr.salary_midpoint IS NOT NULL
),
skill_salary AS (
    SELECT
        js.skill_id,
        COUNT(DISTINCT js.job_id)                                        AS job_count,
        ROUND(AVG(sr.salary_midpoint), 0)                               AS avg_salary,
        ROUND(
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sr.salary_midpoint),
            0
        )                                                                AS median_salary,
        ROUND(
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY sr.salary_midpoint),
            0
        )                                                                AS p75_salary,
        ROUND(
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY sr.salary_midpoint),
            0
        )                                                                AS p25_salary,
        ROUND(MAX(sr.salary_max), 0)                                    AS max_salary_seen
    FROM public.job_skills js
    JOIN public.jobs j
        ON j.job_id = js.job_id
        AND j.is_active = TRUE
        AND j.posted_date >= COALESCE(:start_date, CURRENT_DATE - INTERVAL '12 months')
    JOIN public.salary_ranges sr
        ON sr.job_id       = js.job_id
        AND sr.currency_code = 'USD'
        AND sr.salary_period = 'ANNUAL'
        AND sr.salary_midpoint IS NOT NULL
    GROUP BY js.skill_id
    HAVING COUNT(DISTINCT js.job_id) >= COALESCE(:min_postings, 15)
)
SELECT
    s.skill_name,
    s.skill_category,
    ss.job_count,
    ss.avg_salary,
    ss.median_salary,
    ss.p25_salary,
    ss.p75_salary,
    ss.max_salary_seen,
    bl.overall_median_salary,
    -- Salary premium: how much more (or less) this skill pays vs market median
    (ss.median_salary - bl.overall_median_salary)                        AS salary_premium_abs,
    ROUND(
        (ss.median_salary - bl.overall_median_salary) * 100.0
        / NULLIF(bl.overall_median_salary, 0),
        2
    )                                                                    AS salary_premium_pct,
    -- Rank by median salary
    RANK() OVER (ORDER BY ss.median_salary DESC NULLS LAST)             AS salary_rank,
    -- Rank within skill category
    RANK() OVER (
        PARTITION BY s.skill_category
        ORDER BY ss.median_salary DESC NULLS LAST
    )                                                                    AS salary_rank_in_category
FROM skill_salary ss
JOIN public.skills s
    ON s.skill_id = ss.skill_id
CROSS JOIN baseline_salary bl
ORDER BY
    ss.median_salary DESC NULLS LAST;


-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 9: MOST REQUESTED TECHNOLOGIES (BY SKILL CATEGORY)
-- ─────────────────────────────────────────────────────────────────────────────
-- WHAT   : Demand ranking within each technology category
--          (Programming Language, Cloud Platform, Database, Framework, etc.).
-- WHY    : "Top 5 cloud platforms" or "Top 3 databases" are sliceable views
--          that recruiters and educators find more actionable than a global ranking.
--          A global ranking always shows Python #1 — category breakdowns give
--          nuanced insight into the tool ecosystem.
-- HOW    :
--   FILTER (WHERE js.is_required = TRUE) isolates required skills.
--   required_pct = required_jobs / total_jobs per skill.
--   A skill with high required_pct (>80%) is "table stakes" for the role.
--   A skill with low required_pct (<30%) is "nice to have".
--
--   ROW_NUMBER() OVER (PARTITION BY skill_category ...) gives the rank
--   within each technology category. PARTITION BY is the key:
--   it restarts the rank counter for each new category.
-- ─────────────────────────────────────────────────────────────────────────────

WITH tech_demand AS (
    SELECT
        s.skill_id,
        s.skill_name,
        s.skill_category,
        COUNT(DISTINCT js.job_id)                                        AS total_job_mentions,
        COUNT(DISTINCT js.job_id) FILTER (WHERE js.is_required = TRUE)  AS required_job_mentions,
        COUNT(DISTINCT j.company_id)                                     AS company_count,
        -- MoM trend: compare last 3 months vs prior 3 months
        COUNT(js.job_id) FILTER (
            WHERE j.posted_date >= CURRENT_DATE - INTERVAL '3 months'
        )                                                                AS last_3mo_mentions,
        COUNT(js.job_id) FILTER (
            WHERE j.posted_date >= CURRENT_DATE - INTERVAL '6 months'
                AND j.posted_date < CURRENT_DATE - INTERVAL '3 months'
        )                                                                AS prior_3mo_mentions
    FROM public.job_skills js
    JOIN public.jobs j
        ON j.job_id   = js.job_id
        AND j.is_active = TRUE
    JOIN public.skills s
        ON s.skill_id   = js.skill_id
        AND s.is_active = TRUE
        AND s.skill_category IS NOT NULL   -- Only categorised skills
    WHERE
        j.posted_date >= COALESCE(:start_date, CURRENT_DATE - INTERVAL '12 months')
    GROUP BY
        s.skill_id,
        s.skill_name,
        s.skill_category
),
ranked_tech AS (
    SELECT
        td.*,
        ROUND(
            td.required_job_mentions * 100.0
            / NULLIF(td.total_job_mentions, 0),
            1
        )                                                                AS required_pct,
        -- Trend: growth rate from prior 3mo to last 3mo
        CASE
            WHEN td.prior_3mo_mentions = 0 THEN NULL
            ELSE ROUND(
                (td.last_3mo_mentions - td.prior_3mo_mentions) * 100.0
                / td.prior_3mo_mentions,
                1
            )
        END                                                              AS trend_growth_pct,
        -- Trend label for Power BI conditional formatting
        CASE
            WHEN td.prior_3mo_mentions = 0 THEN 'NEW'
            WHEN td.last_3mo_mentions > td.prior_3mo_mentions * 1.1 THEN 'RISING'
            WHEN td.last_3mo_mentions < td.prior_3mo_mentions * 0.9 THEN 'DECLINING'
            ELSE 'STABLE'
        END                                                              AS trend_label,
        -- Rank within category
        ROW_NUMBER() OVER (
            PARTITION BY td.skill_category
            ORDER BY td.total_job_mentions DESC
        )                                                                AS rank_in_category,
        -- Global rank
        RANK() OVER (ORDER BY td.total_job_mentions DESC)               AS global_rank,
        -- % of total job postings that mention this skill
        ROUND(
            td.total_job_mentions * 100.0
            / NULLIF(
                (SELECT COUNT(*) FROM public.jobs WHERE is_active = TRUE),
                0
            ),
            2
        )                                                                AS pct_of_all_jobs
    FROM tech_demand td
)
SELECT
    skill_category,
    rank_in_category,
    global_rank,
    skill_name,
    total_job_mentions,
    required_job_mentions,
    required_pct,
    company_count,
    last_3mo_mentions,
    prior_3mo_mentions,
    trend_growth_pct,
    trend_label,
    pct_of_all_jobs
FROM ranked_tech
WHERE
    rank_in_category <= COALESCE(:top_per_category, 10)
ORDER BY
    skill_category,
    rank_in_category;


-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 10: SALARY PERCENTILE BANDS BY CANONICAL TITLE
-- ─────────────────────────────────────────────────────────────────────────────
-- WHAT   : For each canonical title, show the full salary distribution:
--          floor (P10), lower quartile (P25), median (P50), upper quartile (P75),
--          ceiling (P90), and the IQR spread.
-- WHY    : This is the "salary band" view that job seekers use to benchmark
--          their offer. A Data Engineer who receives $95k wants to know
--          that P25=$90k, P50=$115k, P75=$140k — not just a single average.
-- HOW    :
--   Multiple PERCENTILE_CONT calls in the same GROUP BY clause are allowed
--   in PostgreSQL — each is computed independently in a single scan.
--   This is more efficient than 5 separate subqueries.
--
--   The "salary_band_width" (P75 - P25) tells us how volatile salaries are
--   for this role. A narrow band = standard market; wide band = specialist or
--   context-dependent role.
--
--   We label each title with a market_tier based on its median relative to
--   the overall median — a CASE WHEN on a window expression.
-- ─────────────────────────────────────────────────────────────────────────────

WITH title_percentiles AS (
    SELECT
        COALESCE(j.canonical_title, 'Other / Unclassified')             AS canonical_title,
        COUNT(DISTINCT j.job_id)                                        AS job_count,
        COUNT(DISTINCT j.company_id)                                    AS company_count,
        ROUND(MIN(sr.salary_min), 0)                                    AS floor_salary,
        ROUND(
            PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY sr.salary_midpoint),
            0
        )                                                               AS p10_salary,
        ROUND(
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY sr.salary_midpoint),
            0
        )                                                               AS p25_salary,
        ROUND(
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY sr.salary_midpoint),
            0
        )                                                               AS p50_median_salary,
        ROUND(AVG(sr.salary_midpoint), 0)                              AS mean_salary,
        ROUND(
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY sr.salary_midpoint),
            0
        )                                                               AS p75_salary,
        ROUND(
            PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY sr.salary_midpoint),
            0
        )                                                               AS p90_salary,
        ROUND(MAX(sr.salary_max), 0)                                   AS ceiling_salary
    FROM public.jobs j
    JOIN public.salary_ranges sr
        ON sr.job_id       = j.job_id
        AND sr.currency_code = 'USD'
        AND sr.salary_period = 'ANNUAL'
        AND sr.salary_midpoint IS NOT NULL
    WHERE
        j.is_active   = TRUE
        AND j.posted_date >= COALESCE(:start_date, CURRENT_DATE - INTERVAL '12 months')
    GROUP BY
        j.canonical_title
    HAVING
        COUNT(DISTINCT j.job_id) >= COALESCE(:min_postings, 20)
)
SELECT
    canonical_title,
    job_count,
    company_count,
    floor_salary,
    p10_salary,
    p25_salary,
    p50_median_salary,
    mean_salary,
    p75_salary,
    p90_salary,
    ceiling_salary,
    -- IQR: spread between lower and upper quartile
    (p75_salary - p25_salary)                                          AS iqr_salary,
    -- Mean vs median skew (positive = right-skewed by high earners)
    (mean_salary - p50_median_salary)                                  AS mean_vs_median_skew,
    -- Overall market median (window — same value on every row)
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY p50_median_salary)
        OVER (),
        0
    )                                                                  AS market_median,
    -- Premium above/below market
    (p50_median_salary - ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY p50_median_salary)
        OVER (),
        0
    ))                                                                 AS premium_vs_market,
    -- Market tier label
    CASE
        WHEN p50_median_salary >= ROUND(
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY p50_median_salary) OVER (),
            0
        ) THEN 'PREMIUM'
        WHEN p50_median_salary >= ROUND(
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY p50_median_salary) OVER (),
            0
        ) THEN 'ABOVE_MARKET'
        WHEN p50_median_salary >= ROUND(
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY p50_median_salary) OVER (),
            0
        ) THEN 'AT_MARKET'
        ELSE 'BELOW_MARKET'
    END                                                                AS market_tier,
    -- Rank by median salary
    RANK() OVER (ORDER BY p50_median_salary DESC NULLS LAST)          AS salary_rank
FROM title_percentiles
ORDER BY
    p50_median_salary DESC NULLS LAST;
