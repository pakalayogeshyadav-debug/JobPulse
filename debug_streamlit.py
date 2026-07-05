import subprocess
import time

import requests

proc = subprocess.Popen(
    ["python", "-m", "streamlit", "run", "app.py", "--server.headless=true", "--server.port=8510"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

time.sleep(3)

try:
    resp = requests.get("http://localhost:8510/")
    print(resp.text[:1000])
except Exception:
    pass

proc.kill()
