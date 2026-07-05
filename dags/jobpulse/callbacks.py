"""
dags/jobpulse/callbacks.py — Airflow callback functions for the JobPulse pipeline.

Every Airflow task and DAG can be given callback hooks that fire on specific
lifecycle events. Centralising them here means every DAG imports from one
place — no duplicated notification logic scattered across multiple DAG files.

Callbacks defined:
    on_failure_notify   — task-level: fires when any task fails
    on_retry_notify     — task-level: fires on each retry attempt
    on_success_notify   — task-level: fires only when a task recovers
    on_dag_failure      — DAG-level : fires when the entire DAG run fails
    on_dag_success      — DAG-level : fires when the entire DAG run succeeds
    on_sla_miss         — DAG-level : fires when a task breaches its SLA

Design Decisions:
    WHY callbacks instead of inline error handling?
        Tasks should be pure business logic. Notification code mixed into
        task functions creates tight coupling — if the notification API changes,
        you'd have to edit every task. Callbacks are injected at the DAG layer.

    WHY email + log (not Slack only)?
        Email is asynchronous, persistent, and archived. Slack is ephemeral.
        The combination ensures both immediate visibility (Slack) and audit
        trail (email). The Slack webhook is optional — if not configured,
        it gracefully degrades to email-only.

    WHY on_retry_notify?
        Retries are often silent failures. Without this callback, a task can
        fail 2 times and succeed on attempt 3 — you'd never know it was flaky.
        Flakiness is a pipeline health signal that ops teams must monitor.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from airflow.models import DagRun, TaskInstance

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Slack webhook URL (optional — loaded from Airflow Variable or env var)
# Set SLACK_WEBHOOK_URL in Airflow → Admin → Variables
# ---------------------------------------------------------------------------
_SLACK_WEBHOOK_URL: str | None = None

try:
    from airflow.models import Variable
    _SLACK_WEBHOOK_URL = Variable.get(
        "JOBPULSE_SLACK_WEBHOOK_URL", default_var=None
    )
except Exception:
    _SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")


# =============================================================================
# Internal helpers
# =============================================================================

def _post_to_slack(message: str) -> None:
    """
    Post a message to Slack via an incoming webhook URL.

    Silently degrades to a log warning if the webhook is not configured
    or if the HTTP request fails. Pipeline notifications should NEVER
    crash the pipeline itself.

    Args:
        message: Plain-text or Slack markdown message body.
    """
    if not _SLACK_WEBHOOK_URL:
        logger.debug("Slack webhook not configured. Skipping Slack notification.")
        return

    try:
        import urllib.request

        payload = json.dumps({"text": message}).encode("utf-8")
        req = urllib.request.Request(
            url=_SLACK_WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                logger.warning(
                    "Slack notification returned non-200 status: %s", resp.status
                )
    except Exception as exc:
        logger.warning("Failed to post Slack notification: %s", exc)


def _format_task_context(context: dict) -> dict[str, str]:
    """
    Extract a clean summary dict from Airflow's task context.

    Args:
        context: The Airflow context dict injected into callbacks.

    Returns:
        dict: Human-readable fields for notification messages.
    """
    ti: TaskInstance = context["task_instance"]
    dag_run: DagRun = context["dag_run"]
    execution_date = context.get("execution_date", datetime.now(tz=UTC))

    return {
        "dag_id":         ti.dag_id,
        "task_id":        ti.task_id,
        "run_id":         dag_run.run_id,
        "execution_date": str(execution_date),
        "log_url":        ti.log_url,
        "try_number":     str(ti.try_number),
        "state":          str(ti.state),
    }


# =============================================================================
# Task-Level Callbacks
# =============================================================================

def on_failure_notify(context: dict) -> None:
    """
    Airflow task on_failure_callback — fires when a task fails (all retries exhausted).

    Sends:
        1. An email via Airflow's built-in email utility (configured in airflow.cfg).
        2. A Slack message (if JOBPULSE_SLACK_WEBHOOK_URL is set).
        3. A structured log entry at ERROR level.

    This callback is attached to every task via default_args in the DAG definition,
    so it fires automatically without being explicitly set on each task.

    Args:
        context: Airflow task context dict.
    """
    info = _format_task_context(context)
    exc = context.get("exception")

    subject = (
        f"🔴 JobPulse FAILED | DAG: {info['dag_id']} | Task: {info['task_id']}"
    )
    body = (
        f"*Pipeline failure detected*\n\n"
        f"  DAG         : {info['dag_id']}\n"
        f"  Task        : {info['task_id']}\n"
        f"  Run ID      : {info['run_id']}\n"
        f"  Exec date   : {info['execution_date']}\n"
        f"  Attempt #   : {info['try_number']}\n"
        f"  Error       : {exc!s}\n"
        f"  Logs        : {info['log_url']}\n\n"
        f"Action required: Check Airflow logs and re-trigger if needed."
    )

    logger.error(
        "TASK FAILURE | dag=%s | task=%s | run=%s | error=%s",
        info["dag_id"], info["task_id"], info["run_id"], exc,
    )

    # Email notification via Airflow's built-in mailer
    try:
        from airflow.utils.email import send_email

        alert_emails = os.getenv(
            "JOBPULSE_ALERT_EMAILS", "data-engineering@yourcompany.com"
        ).split(",")
        send_email(
            to=alert_emails,
            subject=subject,
            html_content=f"<pre>{body}</pre>",
        )
    except Exception as mail_exc:
        logger.warning("Email notification failed: %s", mail_exc)

    _post_to_slack(f"🔴 {subject}\n{body}")


def on_retry_notify(context: dict) -> None:
    """
    Airflow task on_retry_callback — fires on every retry attempt.

    WHY log retries?
        A task that succeeds on attempt 3 is counted as a success in Airflow's UI.
        Silent retries hide flakiness. This callback surfaces them as WARNING
        log entries so ops teams know which tasks are unstable.

    Args:
        context: Airflow task context dict.
    """
    info = _format_task_context(context)
    exc = context.get("exception")

    msg = (
        f"⚠️ RETRY {info['try_number']} | "
        f"DAG: {info['dag_id']} | Task: {info['task_id']} | "
        f"Error: {exc!s}"
    )
    logger.warning(
        "TASK RETRY | dag=%s | task=%s | attempt=%s | error=%s",
        info["dag_id"], info["task_id"], info["try_number"], exc,
    )
    _post_to_slack(f"⚠️ {msg}")


def on_success_notify(context: dict) -> None:
    """
    Airflow task on_success_callback — fires when a previously-failed task recovers.

    In practice, attach this only to critical tasks (e.g., load_jobs_task),
    not to every task, to avoid notification fatigue.

    Args:
        context: Airflow task context dict.
    """
    info = _format_task_context(context)
    logger.info(
        "TASK SUCCESS | dag=%s | task=%s | run=%s",
        info["dag_id"], info["task_id"], info["run_id"],
    )


# =============================================================================
# DAG-Level Callbacks
# =============================================================================

def on_dag_failure(context: dict) -> None:
    """
    Airflow DAG on_failure_callback — fires when the entire DAG run is marked FAILED.

    This fires ONCE per DAG run failure (not per task).
    Use for summaries and escalation (e.g., PagerDuty for production failures).

    Args:
        context: Airflow DAG run context dict.
    """
    dag_run: DagRun = context["dag_run"]

    msg = (
        f"🚨 *JobPulse DAG RUN FAILED*\n"
        f"  DAG      : {dag_run.dag_id}\n"
        f"  Run ID   : {dag_run.run_id}\n"
        f"  Start    : {dag_run.start_date}\n"
        f"  End      : {dag_run.end_date}\n"
        f"  State    : {dag_run.state}\n\n"
        f"Data pipeline is *not fresh*. Investigate immediately."
    )
    logger.error(
        "DAG FAILURE | dag=%s | run=%s | state=%s",
        dag_run.dag_id, dag_run.run_id, dag_run.state,
    )
    _post_to_slack(msg)


def on_dag_success(context: dict) -> None:
    """
    Airflow DAG on_success_callback — fires when the entire DAG run succeeds.

    Logs a structured success summary. Optionally posts to Slack.
    Kept lightweight — verbose on-success notifications cause alert fatigue.

    Args:
        context: Airflow DAG run context dict.
    """
    dag_run: DagRun = context["dag_run"]

    duration = (
        (dag_run.end_date - dag_run.start_date).total_seconds()
        if dag_run.end_date and dag_run.start_date
        else None
    )

    logger.info(
        "DAG SUCCESS | dag=%s | run=%s | duration=%.1fs",
        dag_run.dag_id,
        dag_run.run_id,
        duration or 0.0,
    )
    _post_to_slack(
        f"✅ JobPulse pipeline succeeded | Run: {dag_run.run_id} "
        f"| Duration: {duration:.0f}s" if duration else
        f"✅ JobPulse pipeline succeeded | Run: {dag_run.run_id}"
    )


def on_sla_miss(
    dag,
    task_list,
    blocking_task_list,
    slas,
    blocking_tis,
) -> None:
    """
    Airflow DAG sla_miss_callback — fires when a task breaches its SLA window.

    SLA (Service Level Agreement) in Airflow: a task must complete within
    a specified timedelta after the DAG's schedule interval.

    WHY SLA monitoring?
        A pipeline that runs but takes 6 hours instead of 1 hour is not healthy,
        even if it eventually succeeds. SLA misses signal capacity problems,
        runaway queries, or data volume growth that needs attention.

    Args:
        dag:               The DAG object.
        task_list:         Tasks that missed their SLA.
        blocking_task_list: Tasks blocking further progress.
        slas:              The SLA objects that were missed.
        blocking_tis:      Task instances involved in the miss.
    """
    missed_tasks = [sla.task_id for sla in slas]
    logger.warning(
        "SLA MISS | dag=%s | tasks=%s",
        dag.dag_id, missed_tasks,
    )
    _post_to_slack(
        f"⏰ *SLA Miss* | DAG: {dag.dag_id} | Tasks: {missed_tasks}\n"
        f"Pipeline is running slower than expected."
    )
