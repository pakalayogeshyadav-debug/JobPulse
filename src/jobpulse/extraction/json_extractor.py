"""jobpulse.extraction.json_extractor — JSON File Extractor."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from jobpulse.extraction.base import BaseExtractor, DataExtractionError


class JsonExtractor(BaseExtractor):
    """Extracts job records from a local JSON file."""

    def __init__(
        self,
        file_path: Path | str,
        allow_empty: bool = False,
    ) -> None:
        super().__init__(source_name="json", allow_empty=allow_empty)
        self.file_path = Path(file_path)

    def validate_source(self) -> bool:
        if not self.file_path.exists():
            self._logger.warning("JSON file does not exist: %s", self.file_path)
            return False
        if not self.file_path.is_file():
            self._logger.warning("Path is not a file: %s", self.file_path)
            return False
        return True

    def extract(self) -> pd.DataFrame:
        self._logger.debug("Reading JSON file: %s", self.file_path)
        try:
            with open(self.file_path, encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                # If it's a dict containing a list, try common keys
                if "jobs" in data:
                    data = data["jobs"]
                elif "results" in data:
                    data = data["results"]
                elif "data" in data:
                    data = data["data"]
                else:
                    # Flatten single dict
                    data = [data]

            if not isinstance(data, list):
                raise DataExtractionError(
                    source_name=self.source_name,
                    message="JSON file does not contain a recognizable list of records.",
                )

            df = pd.DataFrame(data)

            # Convert all columns to string to match extraction layer contract
            for col in df.columns:
                df[col] = df[col].astype(str)

            return df

        except DataExtractionError:
            raise
        except json.JSONDecodeError as exc:
            raise DataExtractionError(
                source_name=self.source_name,
                message=f"Failed to parse JSON file: {exc}",
                cause=exc,
            ) from exc
        except Exception as exc:
            raise DataExtractionError(
                source_name=self.source_name,
                message=f"Error reading JSON file: {exc}",
                cause=exc,
            ) from exc
