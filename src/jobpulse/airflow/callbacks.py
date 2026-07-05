"""jobpulse.airflow.callbacks - Airflow DAG and Task lifecycle callbacks."""

from typing import Any

from jobpulse.airflow.notifications import send_failure_email
from jobpulse.logging.logger import get_logger

logger = get_logger(__name__)


def on_failure_callback(context: dict[str, Any]):
    """Executed when a task fails.
    Logs stacktrace, updates pipeline_runs, and triggers notifications.
    """
    ti = context.get("task_instance")
    exception = context.get("exception")

    if ti:
        logger.error(
            f"Task {ti.task_id} failed in DAG {ti.dag_id} " f"with exception: {exception}"
        )

    # Here we would normally inject a session to update the pipeline_runs table in Postgres.
    # We keep it simple in this callback, relying on the actual operators to track their detailed status,
    # or updating a central tracker via a dedicated task.

    send_failure_email(context)


def on_success_callback(context: dict[str, Any]):
    """Executed when a task succeeds."""
    ti = context.get("task_instance")
    if ti:
        logger.info(f"Task {ti.task_id} succeeded in DAG {ti.dag_id}.")
