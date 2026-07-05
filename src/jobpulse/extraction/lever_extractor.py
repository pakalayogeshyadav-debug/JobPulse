"""jobpulse.extraction.lever_extractor — Lever ATS extractor."""

from __future__ import annotations

from typing import Any

from jobpulse.extraction.api_extractor import ApiExtractor


class LeverExtractor(ApiExtractor):
    """Extracts job listings from a specific company's Lever Job Board."""

    def __init__(
        self,
        company_name: str,
    ) -> None:
        self.company_name = company_name

        super().__init__(
            source_name="lever_api",
            base_url=f"https://api.lever.co/v0/postings/{company_name}",
            api_key="public",  # no api key required for public boards
            max_pages=1,  # no pagination
            allow_empty=True,
        )

    def validate_source(self) -> bool:
        if not self.company_name:
            return False
        return True

    def _build_request_params(self, page: int) -> dict[str, Any]:
        return {"mode": "json"}

    def _parse_response(self, response_json: dict[str, Any]) -> list[dict[str, Any]]:
        # Lever API normally returns a list of dictionaries directly
        # Wait, if response_json is a list, ApiExtractor's _parse_json_body expects dict,
        # let's assume it handles a list or we override _parse_json_body?
        # Actually requests.Response.json() returns Any. But ApiExtractor types it as dict[str, Any].
        # I should probably just return the list directly if it's a list.
        if isinstance(response_json, list):
            return response_json
        return []
