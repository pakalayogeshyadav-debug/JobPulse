from src.jobpulse.config.settings import get_settings

settings = get_settings()
print(f"Pydantic sees DB_USER as: {settings.db_user}")
print(f"Pydantic sees DB_PASSWORD as: {settings.db_password}")
print(f"Database URL: {settings.database_url}")
