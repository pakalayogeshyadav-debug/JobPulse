import os
from datetime import datetime

print("Forensic Backup Search...")
ignore_dirs = {".tmp", ".venv", ".git", "__pycache__", "node_modules"}
backup_exts = {".bak", ".old", ".orig", ".save", ".copy"}
backup_dirs = {".history", ".backup", "backup"}

for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in ignore_dirs]
    
    # Check directories
    for d in dirs:
        if d.lower() in backup_dirs:
            print(f"[DIR] {os.path.join(root, d)}")
            
    # Check files
    for f in files:
        if any(f.endswith(ext) for ext in backup_exts) or ".history" in root:
            p = os.path.join(root, f)
            mtime = datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d %H:%M:%S')
            print(f"[FILE] {p} (Modified: {mtime})")
