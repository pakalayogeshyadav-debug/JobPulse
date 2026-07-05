# JobPulse Data Model

The JobPulse Power BI data model is built entirely on a Kimball Star Schema sourced from the Data Warehouse layer. 

## Tables Overview

### Fact Table
- `fact_jobs`: The central fact table representing individual job postings.
  - **Metrics**: `salary_min`, `salary_max`, `is_active`
  - **Granularity**: One row per distinct job posting per source system.

### Dimensions
- `dim_company`: Companies actively hiring.
- `dim_location`: Geographic locations (City, State, Country).
- `dim_skill`: Standardized tech stack skills.
- `dim_date`: Time intelligence dimension covering job posting dates.
- `data_sources`: Operational dimension tracking where the data originated.
- `pipeline_runs`: Operational dimension tracking ETL execution batches.

### Bridge Tables
- `bridge_job_skill`: Resolves the Many-to-Many relationship between `fact_jobs` and `dim_skill`.

## Key Architectural Decisions
- **No Snowflaking**: Dimensions are fully denormalized (e.g., City and State are in `dim_location`, not split out).
- **Import Mode**: The entire model is loaded via Import Mode for blazing fast DAX calculation and sub-second filtering.
- **Surrogate Keys**: All relationships rely on Integer Surrogate Keys (`sk_company_id`, `sk_location_id`) generated in the ETL layer, rather than textual joins.
