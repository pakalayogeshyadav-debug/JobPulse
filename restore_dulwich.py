import os
import shutil

from dulwich.porcelain import reset
from dulwich.repo import Repo

repo_path = r"C:\Users\P Yogesh Yadav\OneDrive\Desktop\DE\jobpulse"

# Clean up the Next.js stuff just to be sure we are back to exactly the old state
web_dir = os.path.join(repo_path, "web")
api_dir = os.path.join(repo_path, "api")
if os.path.exists(web_dir): shutil.rmtree(web_dir, ignore_errors=True)
if os.path.exists(api_dir): shutil.rmtree(api_dir, ignore_errors=True)

repo = Repo(repo_path)
reset(repo, "hard")

print("Hard reset complete via dulwich.")
