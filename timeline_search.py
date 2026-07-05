import json

log_file = r"C:\Users\P Yogesh Yadav\.gemini\antigravity\brain\6a7f514e-b96b-4a43-862d-6fd11cc9fdee\.system_generated\logs\transcript.jsonl"

with open(log_file, encoding="utf-8") as f:
    for line in f:
        try:
            entry = json.loads(line)
        except:
            continue
            
        if entry.get("type") == "USER_INPUT":
            content = entry.get("content", "")
            step = entry.get("step_index")
            print(f"--- STEP {step} ---")
            print(content[:200].replace('\n', ' '))
