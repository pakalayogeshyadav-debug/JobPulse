import urllib.request

try:
    req = urllib.request.Request("http://localhost:8501", headers={'User-Agent': 'Mozilla/5.0'})
    response = urllib.request.urlopen(req, timeout=2)
    print(f"Port 8501 IS ACTIVE. Status: {response.getcode()}")
except Exception as e:
    print(f"Port 8501 is DEAD: {e}")
