import os
import sys
from pathlib import Path

# Fix Windows encoding
sys.stdout.reconfigure(encoding='utf-8')

print("==========================")
print("PHASE 4 - Detect duplicate environments")
print("==========================")
duplicates = []
for p in Path('.').rglob('*'):
    if p.is_file() and (".venv" not in str(p) and ".git" not in str(p)):
        name = p.name.lower()
        if "env" in name or name in ["settings.py", "config.py", "engine.py", "database.py"]:
            print(f"Found: {p.absolute()}")
            duplicates.append(str(p.absolute()))

print("\n==========================")
print("PHASE 2 & 3 - Runtime & Import Tracing")
print("==========================")
try:
    from src.jobpulse.config import settings as settings_mod
    from src.jobpulse.database import engine as engine_mod
    
    print(f"settings.__file__: {settings_mod.__file__}")
    print(f"engine.__file__: {engine_mod.__file__}")
    
    # We must instantiate Settings to trace its loading path
    from dotenv import find_dotenv, load_dotenv
    env_file = find_dotenv(usecwd=True)
    print(f"path of loaded .env: {env_file}")
    
    load_dotenv(env_file, override=True)
    
    settings = settings_mod.Settings()
    
    print(f"current working directory: {os.getcwd()}")
    print(f"absolute path of settings.py: {settings_mod.__file__}")
    print(f"absolute path of engine.py: {engine_mod.__file__}")
    print(f"DB_USER: {settings.db_user}")
    print(f"DB_PASSWORD: {settings.db_password[:1] + '*'*(len(settings.db_password)-2) + settings.db_password[-1:] if settings.db_password else 'NONE'}")
    print(f"DATABASE_URL (settings.database_url): {settings.database_url}")
    print(f"Python executable: {sys.executable}")
    print(f"PID: {os.getpid()}")
except Exception as e:
    print(f"Error tracing modules: {e}")

print("\n==========================")
print("PHASE 1 - Search the entire repository")
print("==========================")
targets = [
    "jobpulse_user", "postgres", "DATABASE_URL", "DB_USER", "DB_PASSWORD",
    "POSTGRES_USER", "create_engine(", "psycopg2.connect",
    "sqlalchemy.create_engine", "localhost:5432", "postgresql://",
    "postgresql+psycopg2://"
]
ignore_dirs = {".git", ".venv", ".tmp", "__pycache__", "node_modules", "logs", "data"}
ignore_exts = {".pyc", ".log", ".jsonl", ".sqlite3", ".exe", ".dll"}

found_jobpulse_user = []

for p in Path('.').rglob('*'):
    if p.is_file() and p.suffix not in ignore_exts:
        if any(ignored in p.parts for ignored in ignore_dirs):
            continue
        try:
            with open(p, encoding='utf-8') as f:
                lines = f.readlines()
                for i, line in enumerate(lines):
                    for t in targets:
                        if t in line:
                            # Keep output small, but explicitly track jobpulse_user
                            if t == "jobpulse_user":
                                found_jobpulse_user.append(f"{p} (Line {i+1}): {line.strip()[:100]}")
                            break
        except Exception:
            pass

print("\nExact occurrences of 'jobpulse_user' in source code:")
for occ in found_jobpulse_user:
    print(occ)
