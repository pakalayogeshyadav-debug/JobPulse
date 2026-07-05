import logging
import sys
from pathlib import Path

# Add src to PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sqlalchemy import inspect

from jobpulse.config.settings import get_settings
from jobpulse.database.engine import create_db_engine
from jobpulse.models import Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_schema():
    logger.info("Loading settings...")
    settings = get_settings()
    
    logger.info(f"Connecting to database {settings.db_name} at {settings.db_host}...")
    engine = create_db_engine(settings)
    
    logger.info("Creating all tables via SQLAlchemy Base.metadata.create_all()...")
    Base.metadata.create_all(engine)
    
    logger.info("Verifying tables exist...")
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    logger.info(f"Found tables: {tables}")
    
    expected_tables = {"data_sources", "pipeline_runs", "jobs"}
    
    missing = expected_tables - set(tables)
    if missing:
        logger.error(f"Missing expected tables: {missing}")
        sys.exit(1)
        
    logger.info("SUCCESS: All Phase 1 tables exist and are synchronized!")

if __name__ == "__main__":
    verify_schema()
