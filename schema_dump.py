from sqlalchemy import inspect
from src.jobpulse.config.settings import Settings
from src.jobpulse.database.engine import create_db_engine

engine = create_db_engine(Settings())
insp = inspect(engine)

for t in insp.get_table_names():
    print(f"Table: {t}")
    for c in insp.get_columns(t):
        print(f"  - {c['name']} ({c['type']})")
    print()
