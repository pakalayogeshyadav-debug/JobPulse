"""jobpulse.validation — Data quality and schema validation sub-package.

Responsible for validating the quality and integrity of DataFrames
AFTER transformation and BEFORE loading into PostgreSQL.

Why Validate?
    Loading bad data into a data warehouse is far worse than not loading it.
    Corrupt data silently propagates into reports and dashboards,
    leading to wrong business decisions.

Validation Categories:
    1. Schema Validation  — Required columns exist and have correct types
    2. Completeness       — Null rate per column is within acceptable limits
    3. Uniqueness         — No duplicate primary/business keys
    4. Range Checks       — Numeric values are within valid ranges
    5. Referential        — Foreign key values exist in dimension tables

Validation Outcome:
    PASS  → DataFrame proceeds to the loading layer
    FAIL  → Pipeline raises DataQualityError and halts (or alerts)
    WARN  → Logged but pipeline continues (configurable)

Future Integration:
    Great Expectations (ge) can replace/extend this layer for richer
    validation, automated documentation, and data observability.

Usage:
    from jobpulse.validation.validator import DataValidator
    validator = DataValidator(config=yaml_config["validation"])
    validator.validate(df)
"""
