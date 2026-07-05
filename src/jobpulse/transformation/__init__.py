"""jobpulse.transformation — Data transformation sub-package.

Responsible for the TRANSFORM step of the ETL pipeline.
Takes raw DataFrames from the extraction layer and produces clean,
standardised DataFrames ready for validation and loading.

What Transformation Does:
    raw (dirty) DataFrame  →  clean (standardised) DataFrame

Transformation Categories:
    1. Cleaning:       Remove nulls, fix encoding, strip whitespace
    2. Normalisation:  Standardise job titles, locations, salary units
    3. Type Casting:   Convert strings to correct types (dates, numbers)
    4. Enrichment:     Derive new columns from existing ones
    5. Deduplication:  Identify and handle duplicate records

Design Principles:
    - Transformers are PURE FUNCTIONS where possible (no side effects)
    - Each transformer handles one concern (single responsibility)
    - Transformations are testable with sample DataFrames
    - Input DataFrames are NEVER mutated — always return a new DataFrame

Transformer Hierarchy:
    BaseTransformer (abstract)
        └── JobListingTransformer   ← Transforms raw job data

Adding a New Transformer:
    1. Create: src/jobpulse/transformation/my_transformer.py
    2. Inherit from BaseTransformer
    3. Implement transform()
"""
