import urllib.request

import psutil

print("==========================")
print("PHASE 7 - Browser / Endpoint Validation")
print("==========================")
try:
    req = urllib.request.Request("http://localhost:8502/healthz", headers={'User-Agent': 'Mozilla/5.0'})
    response = urllib.request.urlopen(req, timeout=5)
    print(f"Health Endpoint Status: {response.getcode()}")
    print(f"Response: {response.read().decode('utf-8')}")
except Exception as e:
    print(f"Healthz failed (normal if not implemented): {e}")

try:
    req = urllib.request.Request("http://localhost:8502", headers={'User-Agent': 'Mozilla/5.0'})
    response = urllib.request.urlopen(req, timeout=5)
    html = response.read().decode('utf-8')
    print(f"Main Page HTTP Status: {response.getcode()}")
    if "jobpulse_user" in html:
        print("ERROR: jobpulse_user found in rendered HTML!")
    else:
        print("SUCCESS: jobpulse_user NOT FOUND in rendered HTML.")
        
    if "password authentication failed" in html:
        print("ERROR: authentication error found in rendered HTML!")
    else:
        print("SUCCESS: No authentication errors present in the HTML payload.")
        
except Exception as e:
    print(f"Failed to fetch main page: {e}")

print("\n==========================")
print("PHASE 9 - Active Streamlit Validation")
print("==========================")
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        if proc.info['cmdline'] and 'streamlit' in ' '.join(proc.info['cmdline']).lower():
            print(f"Found Streamlit -> PID: {proc.info['pid']}, CMD: {' '.join(proc.info['cmdline'])}")
    except:
        pass
