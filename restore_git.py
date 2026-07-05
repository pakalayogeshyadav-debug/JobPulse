import os
import shutil

import git

repo_dir = r"C:\Users\P Yogesh Yadav\OneDrive\Desktop\DE\jobpulse"
repo = git.Repo(repo_dir)

# Ensure frontend directory is deleted before restore
frontend_dir = os.path.join(repo_dir, "frontend")
if os.path.exists(frontend_dir):
    shutil.rmtree(frontend_dir)

# Restore frontend and app.py from HEAD
repo.git.checkout("HEAD", "frontend")
repo.git.checkout("HEAD", "app.py")
repo.git.checkout("HEAD", "docker-compose.yml")

print("Successfully restored frontend, app.py, and docker-compose.yml from HEAD.")
