import os
import re

with open("final_verification.md", encoding="utf-8") as f:
    content = f.read()

# Try to find file paths followed by code blocks.
# Usually looks like: `path/to/file` or ## path/to/file
# followed by ```python ... ```

pattern = re.compile(r'###? `?([^`\n]+)`?\s*\n+```[a-z]*\n(.*?)```', re.DOTALL)
matches = pattern.findall(content)

count = 0
for filepath, code in matches:
    if "frontend" in filepath or "app.py" in filepath:
        # normalize path
        filepath = filepath.strip().strip("`").replace("\\", "/")
        print(f"Found: {filepath}")
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as out:
            out.write(code)
        count += 1

print(f"Restored {count} files from final_verification.md")

# Let's also look for File: `frontend/app.py`
pattern2 = re.compile(r'File: `([^`\n]+)`\s*\n+```[a-z]*\n(.*?)```', re.DOTALL)
matches2 = pattern2.findall(content)
for filepath, code in matches2:
    if "frontend" in filepath or "app.py" in filepath:
        filepath = filepath.strip().strip("`").replace("\\", "/")
        print(f"Found: {filepath}")
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as out:
            out.write(code)
        count += 1
