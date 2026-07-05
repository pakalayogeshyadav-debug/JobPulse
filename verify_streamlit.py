import urllib.request

import psycopg2
from dotenv import load_dotenv
from src.jobpulse.config.settings import Settings

print("==========================")
print("PHASE 7 - End-to-end verification")
print("==========================")
load_dotenv(override=True)
settings = Settings()

print(f"Current DB user: {settings.db_user}")
print(f"Current database: {settings.db_name}")

try:
    conn = psycopg2.connect(
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
        host=settings.db_host,
        port=settings.db_port
    )
    cur = conn.cursor()
    cur.execute("SELECT current_user;")
    print(f"SELECT current_user;: {cur.fetchone()[0]}")
    cur.execute("SELECT current_database();")
    print(f"SELECT current_database();: {cur.fetchone()[0]}")
    conn.close()
except Exception as e:
    print(f"Failed to connect: {e}")

print("\nVerifying Streamlit frontend (http://localhost:8502)...")
try:
    # First request might take a bit if it has to initialize
    req = urllib.request.Request("http://localhost:8502", headers={'User-Agent': 'Mozilla/5.0'})
    response = urllib.request.urlopen(req, timeout=10)
    print(f"Streamlit dashboard HTTP Status: {response.getcode()}")
    html = response.read().decode('utf-8')
    if "Streamlit" in html or "<title>JobPulse" in html or "<noscript>You need to enable JavaScript to run this app.</noscript>" in html:
         print("Dashboard page loaded successfully.")
    else:
         print("Dashboard page loaded but content is unexpected.")
except Exception as e:
    print(f"Failed to load Streamlit dashboard: {e}")
