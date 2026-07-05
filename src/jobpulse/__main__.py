"""jobpulse.__main__ — Allows `python -m jobpulse` execution.

When the package is installed, this module enables running the pipeline
as a module:
    python -m jobpulse

This is the canonical way to run the pipeline in production environments
(e.g., Docker CMD, Airflow BashOperator).
"""

from jobpulse.main import main  # type: ignore[import]

if __name__ == "__main__":
    main()
