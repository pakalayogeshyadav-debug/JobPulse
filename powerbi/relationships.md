# Power BI Relationships

Proper relationship configuration is critical for accurate DAX calculations and avoiding ambiguous filtering paths.

## Primary Star Schema Relationships

All relationships from dimensions to the central `fact_jobs` table are configured as **1-to-Many (1:*)** with **Single Cross-Filter Direction** (Filtering flows from Dimension -> Fact).

| From Table (1) | To Table (*) | Cross-Filter Direction | Active |
|----------------|--------------|-------------------------|--------|
| `dim_company` (sk_company_id) | `fact_jobs` (sk_company_id) | Single | Yes |
| `dim_location` (sk_location_id)| `fact_jobs` (sk_location_id)| Single | Yes |
| `dim_date` (sk_date_id) | `fact_jobs` (sk_posted_date_id)| Single | Yes |
| `data_sources` (data_source_id) | `fact_jobs` (data_source_id) | Single | Yes |

## The Many-to-Many Bridge Resolution

Jobs can have multiple skills, and skills belong to multiple jobs. This is resolved via `bridge_job_skill`.

### Relationship Setup
1. **`fact_jobs` (1) to `bridge_job_skill` (*)**:
   - Key: `sk_fact_job_id`
   - Cross-Filter: **Both (Bi-directional)**
   - *Why?* When a user selects a Skill from `dim_skill`, it filters the bridge, which then must propagate filters back up to `fact_jobs` to recalculate total salaries, etc.

2. **`dim_skill` (1) to `bridge_job_skill` (*)**:
   - Key: `sk_skill_id`
   - Cross-Filter: **Single** (from dim_skill to bridge)

### Performance Note on Bi-Directional Filtering
While bi-directional filtering on the bridge table is required for skill-based slicing, it is strictly limited to this single intersection to prevent ambiguous path errors (the dreaded "Security filter" or circular dependency errors in Power BI).
