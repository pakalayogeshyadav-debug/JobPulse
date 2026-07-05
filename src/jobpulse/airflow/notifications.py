"""jobpulse.airflow.notifications - Airflow email notification functions."""

from airflow.utils.email import send_email


def send_failure_email(context):
    """Sends an email alert when a DAG or Task fails."""
    ti = context.get("task_instance")
    dag_id = ti.dag_id
    task_id = ti.task_id
    log_url = ti.log_url
    execution_date = context.get("execution_date")
    exception = context.get("exception")

    subject = f"[Airflow Alert] DAG {dag_id} - Task {task_id} Failed"

    html_content = f"""
    <h2>Pipeline Failure Alert</h2>
    <p><strong>DAG:</strong> {dag_id}</p>
    <p><strong>Task:</strong> {task_id}</p>
    <p><strong>Execution Date:</strong> {execution_date}</p>
    <p><strong>Exception:</strong> {exception}</p>
    <p><a href="{log_url}">View Airflow Logs</a></p>
    """

    # We retrieve the email list from the task definition
    email_list = ti.task.email
    if email_list:
        send_email(email_list, subject, html_content)
