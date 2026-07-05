import os

from sqlalchemy import create_engine, text

from jobpulse.config.settings import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")

files = [
    "sql/schema/01_create_warehouse_schema.sql",
    "sql/schema/02_create_indexes.sql",
    "sql/views/01_analytical_views.sql",
    "sql/procedures/01_warehouse_elt.sql"
]

with engine.connect() as conn:
    for file in files:
        if os.path.exists(file):
            print(f"Executing {file}...")
            with open(file, encoding='utf-8') as f:
                sql = f.read()
            # Split by statement or just execute the whole block if postgres supports it
            try:
                conn.execute(text(sql))
                print(f"Successfully executed {file}")
            except Exception as e:
                print(f"Error executing {file}: {e}")
        else:
            print(f"File not found: {file}")
