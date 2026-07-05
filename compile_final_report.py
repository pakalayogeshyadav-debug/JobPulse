import glob
import os

with open('evidence.txt', encoding='utf-16') as f:
    evidence_text = f.read()
    
with open('evidence_sql.txt', encoding='utf-8') as f:
    sql_text = f.read()

logs = sorted(glob.glob('logs/*.log'), key=os.path.getmtime, reverse=True)
latest_log = ""
if logs:
    with open(logs[0], encoding='utf-8') as f:
        latest_log = f.read()
        
reports = sorted(glob.glob('reports/data_quality/*.html'), key=os.path.getmtime, reverse=True)
latest_report = ""
if reports:
    with open(reports[0], encoding='utf-8') as f:
        latest_report = f.read()

with open('final_verification.md', 'w', encoding='utf-8') as f:
    f.write("# JobPulse - Final Verification Evidence\n\n")
    f.write("## 1-8, 14-15. Terminal Outputs (main.py, tests, airflow, pip, tree)\n")
    f.write("```text\n")
    # Limiting the output size slightly to avoid blowing up markdown
    f.write(evidence_text)
    f.write("\n```\n\n")
    
    f.write("## 10-13. SQL Warehouse, Views, stored procedures and Power BI\n")
    f.write("```sql\n")
    f.write(sql_text)
    f.write("\n```\n\n")

    f.write("## 16. Pipeline Log (Latest)\n")
    f.write("```log\n")
    f.write(latest_log)
    f.write("\n```\n\n")
    
    f.write("## 17. Validation HTML Report (Head)\n")
    f.write("```html\n")
    f.write(latest_report[:1500] + "\n... [TRUNCATED FOR LENGTH] ...")
    f.write("\n```\n")
