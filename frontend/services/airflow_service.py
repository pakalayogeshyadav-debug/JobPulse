import requests


def get_airflow_status() -> dict:
    hosts = ["localhost", "airflow-webserver"]
    status = {
        "available": False,
        "status": "Offline",
        "message": "Airflow is not reachable.",
        "metadatabase": "unknown",
        "scheduler": "unknown"
    }
    for host in hosts:
        try:
            response = requests.get(f"http://{host}:8080/health", timeout=2)
            if response.status_code == 200:
                data = response.json()
                status["available"] = True
                status["status"] = "Online"
                status["message"] = "Connected"
                status["metadatabase"] = data.get("metadatabase", {}).get("status", "unknown")
                status["scheduler"] = data.get("scheduler", {}).get("status", "unknown")
                return status
        except Exception as e:
            print(f"Failed to fetch Airflow health: {e}")
            continue
    return status
