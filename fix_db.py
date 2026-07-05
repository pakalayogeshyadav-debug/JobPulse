import os

import psycopg2
from dotenv import load_dotenv
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


def fix_postgres_credentials():
    load_dotenv()
    db_name = os.environ.get("DB_NAME", "jobpulse")
    db_user = os.environ.get("DB_USER", "postgres")
    db_pass = os.environ.get("DB_PASSWORD", "Yogi@123")
    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = os.environ.get("DB_PORT", "5432")

    try:
        # Try connecting with desired credentials
        conn = psycopg2.connect(
            dbname=db_name, user=db_user, password=db_pass, host=db_host, port=db_port
        )
        print("✅ Credentials already synchronized. Connection successful.")
        conn.close()
        return
    except psycopg2.OperationalError as e:
        print(f"Failed to connect with .env credentials: {e}")
        print("Attempting to connect with legacy hardcoded credentials to fix...")

    try:
        # Connect using legacy docker-compose default credentials
        legacy_user = "jobpulse_user"
        legacy_pass = "jobpulse_password"
        # Wait, the error message in screenshot said:
        # "password authentication failed for user 'jobpulse_user'"
        # But wait! If the container was built with `your_strong_password_here`, let's try that too.
        
        legacy_passwords = ["your_strong_password_here", "jobpulse_password"]
        conn = None
        for p in legacy_passwords:
            try:
                conn = psycopg2.connect(
                    dbname="jobpulse_dw", user=legacy_user, password=p, host=db_host, port=db_port
                )
                print(f"✅ Connected with legacy user ({legacy_user}). Fixing now...")
                break
            except:
                pass
        
        if not conn:
            print("❌ Could not connect with legacy credentials either. PostgreSQL might not be running or volume is wiped.")
            return

        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        # Check if user exists
        cur.execute(f"SELECT 1 FROM pg_roles WHERE rolname='{db_user}'")
        exists = cur.fetchone()

        if exists:
            print(f"User {db_user} exists. Updating password...")
            cur.execute(f"ALTER ROLE {db_user} WITH PASSWORD '{db_pass}';")
        else:
            print(f"User {db_user} does not exist. Creating...")
            cur.execute(f"CREATE ROLE {db_user} WITH LOGIN SUPERUSER PASSWORD '{db_pass}';")

        # Check if db exists
        cur.execute(f"SELECT 1 FROM pg_database WHERE datname='{db_name}'")
        db_exists = cur.fetchone()
        if not db_exists:
            print(f"Database {db_name} does not exist. Creating...")
            cur.execute(f"CREATE DATABASE {db_name};")
            cur.execute(f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {db_user};")
        
        cur.close()
        conn.close()
        print("✅ Postgres credentials successfully synchronized!")

    except Exception as e:
        print(f"❌ Error while fixing credentials: {e}")

if __name__ == "__main__":
    fix_postgres_credentials()
