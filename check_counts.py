import pandas as pd
from src.jobpulse.config.settings import Settings
from src.jobpulse.database.engine import create_db_engine

engine = create_db_engine(Settings())
tables = ['data_sources', 'jobs', 'pipeline_runs', 'dim_company', 'fact_jobs', 'dim_location', 'dim_date', 'bridge_job_skill', 'dim_skill']
for t in tables:
    try:
        count = pd.read_sql(f'SELECT COUNT(*) as c FROM {t}', engine).iloc[0]['c']
        print(f'{t}: {count}')
    except Exception as e:
        print(f'{t}: ERROR {e}')
