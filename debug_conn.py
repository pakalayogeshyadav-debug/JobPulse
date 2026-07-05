import sys
import os
sys.path.insert(0, 'src')

from dotenv import load_dotenv
load_dotenv(override=True)

from jobpulse.config.settings import Settings
s = Settings()

print("=== DATABASE SETTINGS ===")
print(f"database_url: {s.database_url}")
for attr in dir(s):
    if 'db' in attr.lower() and not attr.startswith('_'):
        try:
            print(f"{attr}: {getattr(s, attr)}")
        except Exception as e:
            print(f"{attr}: ERROR - {e}")

print()
print("=== DIRECT CONNECTION TEST ===")
from jobpulse.database.engine import create_db_engine
from sqlalchemy import text

try:
    engine = create_db_engine(s)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT current_database(), version(), (SELECT COUNT(*) FROM jobs) as job_count"))
        row = result.fetchone()
        print(f"Database: {row[0]}")
        print(f"Version: {row[1][:50]}")
        print(f"Job count: {row[2]}")
    print("CONNECTION: SUCCESS")
except Exception as e:
    print(f"CONNECTION FAILED: {e}")
    import traceback
    traceback.print_exc()
