import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(
    dbname=os.environ.get('DB_NAME', 'jobpulse'),
    user=os.environ.get('DB_USER', 'postgres'),
    password=os.environ.get('DB_PASSWORD', 'Yogi@123'),
    host=os.environ.get('DB_HOST', 'localhost'),
    port=os.environ.get('DB_PORT', '5432')
)
cur = conn.cursor()

print('--- TABLES ---')
cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public';")
print([r[0] for r in cur.fetchall()])

print('\n--- INDEXES ---')
cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public';")
for r in cur.fetchall():
    print(r[0])

print('\n--- CONSTRAINTS ---')
cur.execute("SELECT conname, contype, relname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace JOIN pg_class t ON t.oid = c.conrelid WHERE n.nspname = 'public';")
for r in cur.fetchall():
    print(r)

print('\n--- VIEWS ---')
cur.execute("SELECT viewname FROM pg_views WHERE schemaname = 'public';")
print([r[0] for r in cur.fetchall()])
