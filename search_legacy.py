from pathlib import Path

print("==========================")
print("PHASE 1 - Locate Runtime Credentials")
print("==========================\n")

targets = [
    "jobpulse_user",
    "your_strong_password_here",
    "postgres",
    "Yogi@123",
    "postgresql://",
    "DATABASE_URL",
    "DB_USER",
    "DB_PASSWORD",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD"
]

ignore_dirs = {".git", ".venv", ".tmp", "__pycache__", "node_modules", "logs", "data"}
ignore_exts = {".pyc", ".log", ".jsonl", ".sqlite3"}

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
                            print(f"{p} (Line {i+1}): {line.strip()[:150]}")
                            break
        except Exception:
            pass # ignore binary or encoding errors
