"""Check actual PostgreSQL jobs table schema."""
from jobpulse.config.settings import get_settings
from jobpulse.database.engine import create_db_engine
from sqlalchemy import text

settings = get_settings()
engine = create_db_engine(settings)

with engine.connect() as conn:
    r = conn.execute(text("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = 'jobs' AND table_schema = 'public'
        ORDER BY ordinal_position;
    """))
    print("=== jobs table columns ===")
    for row in r:
        print(f"  {row[0]:25s} {row[1]:20s} nullable={row[2]:4s} default={row[3]}")

    print()
    # Check all tables
    r = conn.execute(text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name;
    """))
    print("=== All tables ===")
    for row in r:
        print(f"  {row[0]}")
