import sys
sys.path.insert(0, 'src')
from dotenv import load_dotenv
load_dotenv()
from jobpulse.database.engine import create_db_engine
from jobpulse.config.settings import Settings
from sqlalchemy import text

engine = create_db_engine(Settings())
with engine.connect() as conn:
    r = conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='pipeline_runs' ORDER BY ordinal_position"
    ))
    print('pipeline_runs columns:', [row[0] for row in r])

    r2 = conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='jobs' ORDER BY ordinal_position"
    ))
    print('jobs columns:', [row[0] for row in r2])

    r3 = conn.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    ))
    print('all tables:', [row[0] for row in r3])

    r4 = conn.execute(text("SELECT COUNT(*) FROM jobs"))
    print('job count:', r4.scalar())

    r5 = conn.execute(text("SELECT COUNT(*) FROM pipeline_runs"))
    print('pipeline run count:', r5.scalar())
