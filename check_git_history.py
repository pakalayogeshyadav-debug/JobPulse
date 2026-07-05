from datetime import datetime

from dulwich.repo import Repo
from dulwich.walk import Walker

repo_path = r"C:\Users\P Yogesh Yadav\OneDrive\Desktop\DE\jobpulse"
try:
    repo = Repo(repo_path)
    print(f"Opened repo at {repo.path}")
    walker = Walker(repo, [repo.head()])
    
    print("\n--- GIT HISTORY ---")
    for i, entry in enumerate(walker):
        if i > 15: # Limit to last 15 commits
            break
        commit = entry.commit
        msg = commit.message.decode('utf-8').strip()
        author = commit.author.decode('utf-8')
        time = datetime.fromtimestamp(commit.commit_time).strftime('%Y-%m-%d %H:%M:%S')
        sha = commit.id.decode('utf-8')
        
        print(f"[{sha[:7]}] {time} - {author}")
        print(f"    {msg}\n")
        
except Exception as e:
    print(f"Failed to read git history: {e}")
