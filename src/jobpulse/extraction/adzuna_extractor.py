"""jobpulse.extraction.adzuna_extractor — Adzuna REST API extractor."""

from __future__ import annotations

import os
from typing import Any

from jobpulse.extraction.api_extractor import ApiExtractor
from jobpulse.extraction.base import DataExtractionError


class AdzunaExtractor(ApiExtractor):
    """Extracts job listings from the public Adzuna API.

    Adzuna uses path-based pagination (e.g., /v1/api/jobs/us/search/1)
    so this class overrides `_fetch_page` to append the page number to the base URL.
    """

    def __init__(
        self,
        app_id: str | None = None,
        app_key: str | None = None,
        country: str = "us",
        results_per_page: int = 50,
        max_pages: int = 10,
    ) -> None:
        self.app_id = app_id or os.getenv("ADZUNA_APP_ID")
        self.app_key = app_key or os.getenv("ADZUNA_APP_KEY")
        self.country = country.lower()
        self.results_per_page = results_per_page

        base_url = f"https://api.adzuna.com/v1/api/jobs/{self.country}/search"

        super().__init__(
            source_name="adzuna_api",
            base_url=base_url,
            api_key=self.app_key or "",
            max_pages=max_pages,
            request_delay_seconds=1.0,
            allow_empty=True,
        )

    def validate_source(self) -> bool:
        if not self.app_id or not self.app_key:
            self._logger.error(
                "Adzuna Extractor requires ADZUNA_APP_ID and ADZUNA_APP_KEY."
            )
            return False
        return super().validate_source()

    def _build_request_params(self, page: int) -> dict[str, Any]:
        return {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": self.results_per_page,
            "content-type": "application/json",
            "_page": page,  # Passed to _fetch_page temporarily
        }

    def _fetch_page(self, params: dict[str, Any]) -> dict[str, Any]:
        page = params.pop("_page", 1)
        paginated_url = f"{self.base_url}/{page}"

        session = self._get_session()
        try:
            response = session.get(
                paginated_url,
                params=params,
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            raise DataExtractionError(
                source_name=self.source_name,
                message=f"Request failed for {paginated_url}",
                cause=exc,
            ) from exc

        self._validate_response_status(response)
        return self._parse_json_body(response)

    def _parse_response(self, response_json: dict[str, Any]) -> list[dict[str, Any]]:
        return response_json.get("results", [])
