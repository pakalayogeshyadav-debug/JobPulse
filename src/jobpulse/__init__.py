"""jobpulse — Job Market Data Engineering Pipeline.

This package provides a modular ETL pipeline for ingesting, transforming,
validating, and loading job market data into a PostgreSQL data warehouse.

Package Structure:
    jobpulse/
    ├── config/          Configuration management (settings, secrets)
    ├── database/        Database engine, session factory, connection handling
    ├── extraction/      Data ingestion from APIs and flat files
    ├── loading/         Writing transformed data to PostgreSQL
    ├── logging/         Structured logging setup
    ├── models/          SQLAlchemy ORM table definitions
    ├── transformation/  Data cleaning, normalisation, and enrichment
    ├── utils/           Shared utility functions and helpers
    └── validation/      Data quality checks and schema validation

Typical Usage:
    from jobpulse.config.settings import get_settings
    from jobpulse.logging.logger import get_logger

    settings = get_settings()
    logger = get_logger(__name__)
"""

__version__ = "0.1.0"
__author__ = "Your Name"
__email__ = "your.email@example.com"
