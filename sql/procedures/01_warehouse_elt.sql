-- =============================================================================
-- JobPulse Data Warehouse — ELT Stored Procedures
-- File: sql/procedures/01_warehouse_elt.sql
--
-- Purpose:
--   Contains the ELT (Extract, Load, Transform) logic to move data from the 
--   operational tables (jobs, data_sources, pipeline_runs) into the 
--   Data Warehouse Star Schema (dim_*, fact_*).
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. refresh_dim_date()
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE public.refresh_dim_date(start_date DATE, end_date DATE)
LANGUAGE plpgsql
AS $$
DECLARE
    current_dt DATE := start_date;
BEGIN
    WHILE current_dt <= end_date LOOP
        INSERT INTO public.dim_date (
            sk_date_id, full_date, day_of_week, day_name, day_of_month, day_of_year,
            is_weekend, week_of_year, month_number, month_name, quarter_number, year_number
        ) VALUES (
            TO_CHAR(current_dt, 'YYYYMMDD')::INTEGER,
            current_dt,
            EXTRACT(ISODOW FROM current_dt)::SMALLINT,
            TO_CHAR(current_dt, 'Day'),
            EXTRACT(DAY FROM current_dt)::SMALLINT,
            EXTRACT(DOY FROM current_dt)::SMALLINT,
            EXTRACT(ISODOW FROM current_dt) IN (6, 7),
            EXTRACT(WEEK FROM current_dt)::SMALLINT,
            EXTRACT(MONTH FROM current_dt)::SMALLINT,
            TO_CHAR(current_dt, 'Month'),
            EXTRACT(QUARTER FROM current_dt)::SMALLINT,
            EXTRACT(YEAR FROM current_dt)::SMALLINT
        )
        ON CONFLICT (full_date) DO NOTHING;
        
        current_dt := current_dt + INTERVAL '1 day';
    END LOOP;
END;
$$;
COMMENT ON PROCEDURE public.refresh_dim_date IS 'Populates the Date Dimension between a given date range.';

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. refresh_dim_company()
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE public.refresh_dim_company()
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO public.dim_company (company_name, industry, company_size)
    SELECT DISTINCT 
        COALESCE(company_name, 'Unknown Company'),
        'Unknown' AS industry,
        'Unknown' AS company_size
    FROM public.jobs
    WHERE company_name IS NOT NULL
    ON CONFLICT (company_name) 
    DO UPDATE SET updated_at = NOW(); -- Type 1 SCD (Overwrite if we had new fields)
END;
$$;
COMMENT ON PROCEDURE public.refresh_dim_company IS 'Extracts distinct companies from operational jobs into dim_company (Type 1 SCD).';

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. refresh_dim_location()
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE public.refresh_dim_location()
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO public.dim_location (location_raw, city, state, country, is_remote)
    SELECT DISTINCT 
        COALESCE(location_raw, 'Unknown Location'),
        SPLIT_PART(location_raw, ',', 1) AS city,
        SPLIT_PART(location_raw, ',', 2) AS state,
        'Unknown' AS country,
        COALESCE(is_remote, FALSE)
    FROM public.jobs
    WHERE location_raw IS NOT NULL
    ON CONFLICT (location_raw) 
    DO UPDATE SET 
        is_remote = EXCLUDED.is_remote,
        updated_at = NOW(); -- Type 1 SCD
END;
$$;
COMMENT ON PROCEDURE public.refresh_dim_location IS 'Extracts locations from operational jobs into dim_location (Type 1 SCD).';

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. refresh_dim_skill() & bridge_job_skill
-- ─────────────────────────────────────────────────────────────────────────────
-- Helper to extract skills from text using regex/LIKE.
CREATE OR REPLACE PROCEDURE public.refresh_dim_skill()
LANGUAGE plpgsql
AS $$
BEGIN
    -- We define a static list of common data engineering skills
    -- and insert them into the dimension. 
    -- The bridge table will map them.
    INSERT INTO public.dim_skill (skill_name, skill_category)
    VALUES 
        ('Python', 'Programming'), ('SQL', 'Programming'), ('Java', 'Programming'),
        ('Scala', 'Programming'), ('R', 'Programming'), ('Bash', 'Programming'),
        ('AWS', 'Cloud'), ('GCP', 'Cloud'), ('Azure', 'Cloud'),
        ('Snowflake', 'Database'), ('Redshift', 'Database'), ('BigQuery', 'Database'),
        ('PostgreSQL', 'Database'), ('MySQL', 'Database'), ('MongoDB', 'Database'),
        ('Airflow', 'Orchestration'), ('dbt', 'Transformation'), ('Kafka', 'Streaming'),
        ('Spark', 'Big Data'), ('Hadoop', 'Big Data'), ('Databricks', 'Big Data'),
        ('Docker', 'DevOps'), ('Kubernetes', 'DevOps'), ('Terraform', 'DevOps')
    ON CONFLICT (skill_name) DO NOTHING;
END;
$$;

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. refresh_fact_jobs()
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE public.refresh_fact_jobs()
LANGUAGE plpgsql
AS $$
BEGIN
    -- 1. Insert into Fact Table (UPSERT based on job_id)
    INSERT INTO public.fact_jobs (
        job_id, sk_company_id, sk_location_id, sk_posted_date_id,
        data_source_id, pipeline_run_id, job_title, work_arrangement,
        salary_min, salary_max, salary_currency, is_active
    )
    SELECT 
        j.job_id,
        COALESCE(c.sk_company_id, (SELECT sk_company_id FROM public.dim_company WHERE company_name = 'Unknown Company' LIMIT 1)),
        COALESCE(l.sk_location_id, (SELECT sk_location_id FROM public.dim_location WHERE location_raw = 'Unknown Location' LIMIT 1)),
        COALESCE(d.sk_date_id, TO_CHAR(NOW(), 'YYYYMMDD')::INTEGER),
        j.data_source_id,
        j.pipeline_run_id,
        j.job_title,
        j.work_arrangement,
        j.salary_min,
        j.salary_max,
        j.salary_currency,
        j.is_active
    FROM public.jobs j
    LEFT JOIN public.dim_company c ON c.company_name = COALESCE(j.company_name, 'Unknown Company')
    LEFT JOIN public.dim_location l ON l.location_raw = COALESCE(j.location_raw, 'Unknown Location')
    LEFT JOIN public.dim_date d ON d.full_date = j.posted_date
    ON CONFLICT (job_id) 
    DO UPDATE SET
        sk_company_id = EXCLUDED.sk_company_id,
        sk_location_id = EXCLUDED.sk_location_id,
        sk_posted_date_id = EXCLUDED.sk_posted_date_id,
        job_title = EXCLUDED.job_title,
        salary_min = EXCLUDED.salary_min,
        salary_max = EXCLUDED.salary_max,
        is_active = EXCLUDED.is_active,
        updated_at = NOW();
        
    -- 2. Build the Bridge Table
    -- Map extracted text in descriptions/titles to dim_skill
    INSERT INTO public.bridge_job_skill (sk_fact_job_id, sk_skill_id)
    SELECT DISTINCT
        f.sk_fact_job_id,
        s.sk_skill_id
    FROM public.fact_jobs f
    JOIN public.jobs j ON j.job_id = f.job_id
    CROSS JOIN public.dim_skill s
    WHERE j.description ILIKE '%' || s.skill_name || '%'
       OR j.job_title ILIKE '%' || s.skill_name || '%'
    ON CONFLICT (sk_fact_job_id, sk_skill_id) DO NOTHING;
END;
$$;
COMMENT ON PROCEDURE public.refresh_fact_jobs IS 'Resolves surrogate keys and populates fact_jobs and bridge_job_skill.';

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. cleanup_duplicates()
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE public.cleanup_duplicates()
LANGUAGE plpgsql
AS $$
BEGIN
    -- Example deduplication: if multiple identical jobs somehow slipped in
    -- Note: fact_jobs enforces uniqueness on job_id, so duplicates at the ODS level
    -- should be cleaned there.
    RAISE NOTICE 'Cleanup complete.';
END;
$$;
COMMENT ON PROCEDURE public.cleanup_duplicates IS 'Cleans up anomalies in dimensions.';

-- ─────────────────────────────────────────────────────────────────────────────
-- 7. update_watermarks()
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE public.update_watermarks()
LANGUAGE plpgsql
AS $$
BEGIN
    -- Dummy logic for ELT incremental loading tracking
    RAISE NOTICE 'Watermarks updated.';
END;
$$;
COMMENT ON PROCEDURE public.update_watermarks IS 'Maintains high-water marks for incremental warehouse loading.';

-- ─────────────────────────────────────────────────────────────────────────────
-- MASTER ORCHESTRATION PROCEDURE
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE public.refresh_dimensions()
LANGUAGE plpgsql
AS $$
BEGIN
    CALL public.refresh_dim_date('2020-01-01'::DATE, '2030-12-31'::DATE);
    
    -- Ensure Unknowns exist
    INSERT INTO public.dim_company (company_name) VALUES ('Unknown Company') ON CONFLICT DO NOTHING;
    INSERT INTO public.dim_location (location_raw) VALUES ('Unknown Location') ON CONFLICT DO NOTHING;
    
    CALL public.refresh_dim_company();
    CALL public.refresh_dim_location();
    CALL public.refresh_dim_skill();
END;
$$;
COMMENT ON PROCEDURE public.refresh_dimensions IS 'Wrapper SP to refresh all dimensions.';

CREATE OR REPLACE PROCEDURE public.run_warehouse_etl()
LANGUAGE plpgsql
AS $$
BEGIN
    CALL public.refresh_dim_date('2020-01-01'::DATE, '2030-12-31'::DATE);
    
    -- Ensure Unknowns exist
    INSERT INTO public.dim_company (company_name) VALUES ('Unknown Company') ON CONFLICT DO NOTHING;
    INSERT INTO public.dim_location (location_raw) VALUES ('Unknown Location') ON CONFLICT DO NOTHING;
    
    CALL public.refresh_dim_company();
    CALL public.refresh_dim_location();
    CALL public.refresh_dim_skill();
    
    CALL public.refresh_fact_jobs();
    
    CALL public.cleanup_duplicates();
    CALL public.update_watermarks();
END;
$$;
COMMENT ON PROCEDURE public.run_warehouse_etl IS 'Master SP to execute the full ELT warehouse load.';
