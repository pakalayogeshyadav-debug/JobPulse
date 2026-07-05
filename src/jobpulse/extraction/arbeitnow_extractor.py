"""jobpulse.extraction.arbeitnow_extractor — Arbeitnow REST API extractor."""

from __future__ import annotations

from typing import Any

from jobpulse.extraction.api_extractor import ApiExtractor


class ArbeitnowExtractor(ApiExtractor):
    """Extracts remote job listings from the public Arbeitnow API."""

    def __init__(
        self,
        max_pages: int = 10,
    ) -> None:

        super().__init__(
            source_name="arbeitnow_api",
            base_url="https://www.arbeitnow.com/api/job-board-api",
            api_key="public",  # no api key required
            max_pages=max_pages,
            allow_empty=True,
        )

    def validate_source(self) -> bool:
        return True  # Public API

    def _build_request_params(self, page: int) -> dict[str, Any]:
        return {"page": page}

    def _parse_response(self, response_json: dict[str, Any]) -> list[dict[str, Any]]:
        return response_json.get("data", [])
