$ErrorActionPreference = "Continue"
$Env:PYTHONIOENCODING = "utf8"
$Env:PYTHONUNBUFFERED = "1"

echo "=========================================" > evidence.txt
echo "1. Output of python main.py" >> evidence.txt
.venv\Scripts\python.exe main.py >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "2. Output of python verify_schema.py" >> evidence.txt
.venv\Scripts\python.exe verify_schema.py >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "3. Output of pytest -v" >> evidence.txt
.venv\Scripts\pytest.exe -v >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "4. Output of pytest --cov" >> evidence.txt
.venv\Scripts\pytest.exe --cov >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "5. Output of pip check" >> evidence.txt
.venv\Scripts\pip.exe check >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "6. Output of docker compose ps" >> evidence.txt
docker compose ps >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "7. Output of airflow dags list" >> evidence.txt
.venv\Scripts\python.exe run_airflow_cli.py dags list >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "8. Output of airflow tasks test jobpulse_daily_etl health_check_db" >> evidence.txt
.venv\Scripts\python.exe run_airflow_cli.py tasks test jobpulse_daily_etl health_check_db 2024-01-01 >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "14. Exact final dependency versions" >> evidence.txt
.venv\Scripts\pip.exe freeze >> evidence.txt 2>&1

echo "`n=========================================" >> evidence.txt
echo "15. Final repository tree" >> evidence.txt
tree /F /A >> evidence.txt 2>&1
