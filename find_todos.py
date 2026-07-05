import os

directory = r"c:\Users\P Yogesh Yadav\OneDrive\Desktop\DE\jobpulse\src\jobpulse\extraction"
for root, _, files in os.walk(directory):
    for f in files:
        if f.endswith(".py"):
            path = os.path.join(root, f)
            with open(path, encoding="utf-8") as file:
                lines = file.readlines()
                for i, line in enumerate(lines):
                    if "TODO" in line or "pass" in line.strip().split():
                        print(f"{f}:{i+1}: {line.strip()}")
