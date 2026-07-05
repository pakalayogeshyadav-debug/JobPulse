$ErrorActionPreference = "Continue"
$Env:PYTHONIOENCODING = "utf8"
$Env:PYTHONUNBUFFERED = "1"
$Env:PYTHONPATH = "src"

echo "=========================================" > evidence.txt
echo "1. Output of python main.py" >> evidence.txt
python main.py >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "2. Output of python verify_schema.py" >> evidence.txt
python verify_schema.py >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "3. Output of pytest -v" >> evidence.txt
python -m pytest -v >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "4. Output of pytest --cov" >> evidence.txt
python -m pytest --cov >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "5. Output of pip check" >> evidence.txt
python -m pip check >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "6. Output of docker compose ps" >> evidence.txt
echo "Docker is not natively available in this environment. Database is running natively on localhost." >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "7. Output of airflow dags list" >> evidence.txt
echo "Airflow fails natively on Windows due to fcntl missing. It must be run via Docker or WSL." >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "8. Output of airflow tasks test jobpulse_daily_etl health_check_db" >> evidence.txt
echo "Airflow fails natively on Windows due to fcntl missing. It must be run via Docker or WSL." >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "14. Exact final dependency versions" >> evidence.txt
python -m pip freeze >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "15. Final repository tree" >> evidence.txt
tree /F /A >> evidence.txt 2>&1
