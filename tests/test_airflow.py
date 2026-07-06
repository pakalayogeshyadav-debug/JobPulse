"""Tests for Airflow DAGs and Operators."""

# ruff: noqa: E402,S110

import inspect
import os
import sys
from pathlib import Path

# Ensure Airflow binds to a workspace-local metadata DB before any Airflow import.
AIRFLOW_HOME = Path(__file__).parent.parent.absolute() / "airflow_home"
AIRFLOW_HOME.mkdir(exist_ok=True)
os.environ["AIRFLOW_HOME"] = str(AIRFLOW_HOME)
os.environ["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"] = (
    f"sqlite:///{(AIRFLOW_HOME / 'airflow.db').as_posix()}"
)
# Tell Airflow never to load bundled example DAGs — works across all versions.
os.environ["AIRFLOW__CORE__LOAD_EXAMPLES"] = "False"

# Windows compatibility for Airflow imports (mocks fcntl)
if os.name == "nt":
    import types

    fcntl = types.ModuleType("fcntl")
    fcntl.ioctl = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    fcntl.flock = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    fcntl.lockf = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    fcntl.LOCK_EX = 2  # type: ignore[attr-defined]
    fcntl.LOCK_SH = 1  # type: ignore[attr-defined]
    fcntl.LOCK_NB = 4  # type: ignore[attr-defined]
    fcntl.LOCK_UN = 8  # type: ignore[attr-defined]
    sys.modules["fcntl"] = fcntl

    # Mock timeout context managers to avoid signal.SIGALRM on Windows
    import contextlib

    @contextlib.contextmanager
    def mock_timeout(*args, **kwargs):
        yield

    class MockTimeoutClass:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    try:
        import airflow.utils.db

        airflow.utils.db.timeout_with_traceback = mock_timeout
    except Exception:
        pass

    try:
        import airflow.utils.timeout

        airflow.utils.timeout.timeout = MockTimeoutClass
    except Exception:
        pass

    try:
        import airflow.dag_processing.importers.python_importer

        airflow.dag_processing.importers.python_importer._timeout = mock_timeout
    except Exception:
        pass

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dag_bag(dags_dir: Path):
    """Create a DagBag that works across Airflow 2.x and 3.x.

    Airflow 2.x removed the ``include_examples`` constructor argument from
    ``DagBag`` — the setting is controlled exclusively through the env var
    ``AIRFLOW__CORE__LOAD_EXAMPLES``.  Airflow 3.x re-added it.  We detect
    the available parameters at import time and call accordingly so the same
    test file works with any installed version.
    """
    from airflow.models import DagBag

    params = inspect.signature(DagBag.__init__).parameters
    if "include_examples" in params:
        return DagBag(dag_folder=str(dags_dir), include_examples=False)
    # Older Airflow 2.x: rely on the env var set above.
    return DagBag(dag_folder=str(dags_dir))


# ---------------------------------------------------------------------------
# Session-scoped DB initialisation
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def setup_airflow_db():
    """Initialise the Airflow metadata database.

    Tries the modern ``upgradedb`` first, then falls back to ``initdb`` for
    older Airflow releases that don't expose ``upgradedb``.
    """
    import airflow.utils.db as af_db

    if hasattr(af_db, "upgradedb"):
        af_db.upgradedb()
    elif hasattr(af_db, "initdb"):
        af_db.initdb()
    # If neither exists the DB is likely already initialised — continue.


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dag_loading_no_errors():
    """Test that all DAGs in the dags/ folder load without errors."""
    dags_dir = Path(__file__).parent.parent / "dags"
    dag_bag = _make_dag_bag(dags_dir)

    assert (
        len(dag_bag.import_errors) == 0
    ), f"DAG import errors: {dag_bag.import_errors}"


def test_pipeline_dag_structure():
    """Test the structure of the main jobpulse_pipeline DAG."""
    dags_dir = Path(__file__).parent.parent / "dags"
    dag_bag = _make_dag_bag(dags_dir)

    dag = dag_bag.get_dag(dag_id="jobpulse_daily_etl")
    assert dag is not None

    # Check tasks exist
    task_ids = [t.task_id for t in dag.tasks]
    assert "extract_data" in task_ids
    assert "transform_data" in task_ids
    assert "validate_data" in task_ids
    assert "load_db" in task_ids
    assert "warehouse_elt.update_dimensions" in task_ids

    # Check dependencies (extract -> transform -> validate -> load)
    extract_task = dag.get_task("extract_data")
    transform_task = dag.get_task("transform_data")
    validate_task = dag.get_task("validate_data")

    assert "transform_data" in [t.task_id for t in extract_task.downstream_list]
    assert "validate_data" in [t.task_id for t in transform_task.downstream_list]
    assert "load_db" in [t.task_id for t in validate_task.downstream_list]


def test_incremental_dag_structure():
    dags_dir = Path(__file__).parent.parent / "dags"
    dag_bag = _make_dag_bag(dags_dir)

    dag = dag_bag.get_dag(dag_id="jobpulse_incremental_etl")
    assert dag is not None


def test_backfill_dag_structure():
    dags_dir = Path(__file__).parent.parent / "dags"
    dag_bag = _make_dag_bag(dags_dir)

    dag = dag_bag.get_dag(dag_id="jobpulse_backfill_etl")
    assert dag is not None
