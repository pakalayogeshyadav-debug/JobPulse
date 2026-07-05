"""jobpulse.extraction.greenhouse_extractor — Greenhouse ATS extractor."""

from __future__ import annotations

from typing import Any

from jobpulse.extraction.api_extractor import ApiExtractor


class GreenhouseExtractor(ApiExtractor):
    """Extracts job listings from a specific company's Greenhouse Job Board."""

    def __init__(
        self,
        board_token: str,
    ) -> None:
        self.board_token = board_token

        super().__init__(
            source_name="greenhouse_api",
            base_url=f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs",
            api_key="public",  # no api key required for public boards
            max_pages=1,  # no pagination
            allow_empty=True,
        )

    def validate_source(self) -> bool:
        if not self.board_token:
            return False
        return True

    def _build_request_params(self, page: int) -> dict[str, Any]:
        return {"content": "true"}

    def _parse_response(self, response_json: dict[str, Any]) -> list[dict[str, Any]]:
        return response_json.get("jobs", [])
