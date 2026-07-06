import os

from dulwich.repo import Repo

try:
    repo = Repo(".")
    print("Found repo:", repo.path)
    print("Head:", repo.head())
    
    # Let's list files in the HEAD tree
    tree = repo[repo.head()].tree
    def print_tree(tree_id, path=""):
        for entry in repo[tree_id].items():
            full_path = os.path.join(path, entry.path.decode('utf-8'))
            print(full_path)
            if entry.mode == 0o040000: # Directory
                print_tree(entry.sha, full_path)
                
    print_tree(tree)
except Exception as e:
    print("Error:", e)
