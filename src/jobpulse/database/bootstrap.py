"""jobpulse.database.bootstrap — Database startup validation and initialization."""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.engine import Engine

from jobpulse.exceptions import SchemaMismatchError
from jobpulse.logging.logger import get_logger
from jobpulse.models.base import Base
from jobpulse.database.seed import seed_reference_data
from jobpulse.database.sequence_sync import sync_sequences

logger = get_logger(__name__)


def validate_schema(engine: Engine) -> None:
    """Verify that ORM models perfectly match the live PostgreSQL schema."""
    logger.info("Validating database schema...")
    db_metadata = MetaData()
    db_metadata.reflect(bind=engine)
    
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        table = mapper.local_table
        table_name = table.name
        
        if table_name not in db_metadata.tables:
            raise SchemaMismatchError(f"Missing table in database: {table_name}")
            
        db_table = db_metadata.tables[table_name]
        
        orm_columns = set(c.name for c in table.columns)
        db_columns = set(c.name for c in db_table.columns)
        
        missing_in_db = orm_columns - db_columns
        extra_in_db = db_columns - orm_columns
        
        if missing_in_db or extra_in_db:
            err_msgs = []
            if missing_in_db:
                err_msgs.append(f"Missing in DB: {', '.join(missing_in_db)}")
            if extra_in_db:
                err_msgs.append(f"Extra in DB: {', '.join(extra_in_db)}")
                
            raise SchemaMismatchError(
                f"Schema drift detected in table '{table_name}': " + "; ".join(err_msgs)
            )

    logger.info("Schema validation passed: ORM matches database.")


def bootstrap_database(engine: Engine) -> None:
    """Run all startup initialization checks and seeders.
    
    1. Verify all required tables exist.
    2. Validate ORM vs Database schema.
    3. Seed reference tables.
    4. Synchronize all PostgreSQL sequences.
    
    Aborts startup (raises Exception) if initialization fails.
    """
    logger.info("Starting database bootstrap...")
    
    # Optional: Base.metadata.create_all(engine)
    # But we assume schema.sql is the source of truth, so we just validate
    
    try:
        # Phase 1: Validate Schema
        validate_schema(engine)
        
        # Phase 2: Seed reference data
        seed_reference_data(engine)
        
        # Phase 3: Sync sequences
        sync_sequences(engine)
        
        logger.info("Database bootstrap completed successfully.")
    except Exception as e:
        logger.error(f"Database bootstrap failed: {e}")
        raise
