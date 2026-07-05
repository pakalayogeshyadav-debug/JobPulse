import os
import sys
from pathlib import Path

import psycopg2

# Fix Windows encoding issue
sys.stdout.reconfigure(encoding='utf-8')

# PHASE 3: Verify Which .env Is Loaded
print("==========================")
print("PHASE 3 - .env Verification")
print("==========================")
env_paths = list(Path('.').rglob('.env'))
print("Found .env files:")
for p in env_paths:
    if ".venv" not in str(p) and ".git" not in str(p):
        print(f" - {p.absolute()}")

from dotenv import find_dotenv, load_dotenv

env_file = find_dotenv()
print(f"dotenv is loading: {env_file}")
load_dotenv(env_file, override=True)

# PHASE 2: Print Runtime Configuration
print("\n==========================")
print("PHASE 2 - Runtime Config")
print("==========================")
db_host = os.environ.get("DB_HOST", "localhost")
db_port = os.environ.get("DB_PORT", "5432")
db_name = os.environ.get("DB_NAME", "jobpulse_dw")
db_user = os.environ.get("DB_USER", "jobpulse_user")
db_pass = os.environ.get("DB_PASSWORD", "your_strong_password_here")

def mask(s):
    if not s or len(s) < 3: return "***"
    return f"{s[0]}{'*' * (len(s)-2)}{s[-1]}"

print(f"DB_HOST: {db_host}")
print(f"DB_PORT: {db_port}")
print(f"DB_NAME: {db_name}")
print(f"DB_USER: {db_user}")
print(f"DB_PASSWORD: {mask(db_pass)}")
print(f"DATABASE_URL: postgresql://{db_user}:***@{db_host}:{db_port}/{db_name}")

# PHASE 6: Test Credentials Directly
print("\n==========================")
print("PHASE 6 & 5 - Direct psycopg2 Test")
print("==========================")
try:
    conn = psycopg2.connect(
        dbname=db_name,
        user=db_user,
        password=db_pass,
        host=db_host,
        port=db_port
    )
    print(f"[OK] Connected directly using {db_user} to {db_name}")
    
    cur = conn.cursor()
    cur.execute("SELECT rolname FROM pg_roles;")
    roles = [r[0] for r in cur.fetchall()]
    print(f"Available users in pg_roles: {roles}")
    
    if "jobpulse_user" in roles:
        print("-> jobpulse_user EXISTS in the DB.")
    else:
        print("-> jobpulse_user DOES NOT EXIST in the DB.")
        
    cur.close()
    conn.close()
except Exception as e:
    print(f"[ERROR] Connection failed! Reason:\n{e}")
