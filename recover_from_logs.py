import json
import os
import sys


def restore_to_step(target_step):
    log_file = r"C:\Users\P Yogesh Yadav\.gemini\antigravity\brain\6a7f514e-b96b-4a43-862d-6fd11cc9fdee\.system_generated\logs\transcript.jsonl"
    
    file_contents = {}
    
    print(f"Reading logs up to step {target_step}...")
    with open(log_file, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except Exception:
                continue
                
            step = entry.get("step_index")
            if step > target_step:
                break
                
            if entry.get("source") != "MODEL":
                continue
                
            tool_calls = entry.get("tool_calls", [])
            for call in tool_calls:
                name = call.get("name")
                args = call.get("args", {})
                
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except:
                        continue
                
                if name == "write_to_file":
                    filepath = args.get("TargetFile", "")
                    if filepath:
                        filepath = filepath.strip('"').replace("\\", "/")
                        content = args.get("CodeContent", "").strip('"')
                        if content.startswith('"') and content.endswith('"'):
                            try:
                                content = json.loads(content)
                            except:
                                pass
                        
                        if isinstance(content, str):
                            content = content.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t")
                        file_contents[filepath] = content
                        
                elif name == "replace_file_content":
                    filepath = args.get("TargetFile", "")
                    if filepath:
                        filepath = filepath.strip('"').replace("\\", "/")
                        target = args.get("TargetContent", "")
                        repl = args.get("ReplacementContent", "")
                        if isinstance(target, str) and target.startswith('"'): target = target.strip('"').replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t")
                        if isinstance(repl, str) and repl.startswith('"'): repl = repl.strip('"').replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t")
                        
                        if filepath in file_contents:
                            file_contents[filepath] = file_contents[filepath].replace(target, repl)

    # Now write them out
    count = 0
    for p, content in file_contents.items():
        if "C:/Users/P Yogesh Yadav/OneDrive/Desktop/DE/jobpulse" in p or "c:/Users/P Yogesh Yadav/OneDrive/Desktop/DE/jobpulse" in p:
            out_path = p.replace("C:/Users/P Yogesh Yadav/OneDrive/Desktop/DE/jobpulse/", "").replace("c:/Users/P Yogesh Yadav/OneDrive/Desktop/DE/jobpulse/", "")
            
            # Skip artifacts
            if ".gemini" in out_path:
                continue
                
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as out:
                out.write(content)
            count += 1
            print(f"Restored: {out_path}")
            
    print(f"Successfully restored {count} files as they were at step {target_step}.")

if __name__ == "__main__":
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 312
    restore_to_step(target)
