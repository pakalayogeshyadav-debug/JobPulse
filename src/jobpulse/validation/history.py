"""jobpulse.validation.history — Persists validation history."""

import csv
import os
from pathlib import Path

from jobpulse.validation.report import ValidationReport


def save_validation_history(
    report: ValidationReport, run_id: str, output_dir: str = "data"
) -> None:
    """Appends the validation run results to a historical CSV log."""
    os.makedirs(output_dir, exist_ok=True)
    history_file = Path(output_dir) / "validation_history.csv"

    file_exists = history_file.is_file()

    with open(history_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(
                [
                    "run_id",
                    "timestamp",
                    "rows_checked",
                    "rows_failed",
                    "success_rate",
                    "execution_time",
                ]
            )

        writer.writerow(
            [
                run_id,
                report.timestamp,
                report.rows_checked,
                report.rows_invalid,
                f"{report.success_rate:.4f}",
                f"{report.execution_time:.4f}",
            ]
        )
