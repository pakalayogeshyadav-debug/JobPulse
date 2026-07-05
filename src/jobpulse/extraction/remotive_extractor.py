"""jobpulse.extraction.remotive_extractor — Remotive REST API extractor."""

from __future__ import annotations

from typing import Any

from jobpulse.extraction.api_extractor import ApiExtractor


class RemotiveExtractor(ApiExtractor):
    """Extracts remote job listings from the public Remotive API.

    Note: Remotive does not use pagination, it returns all jobs for a category at once.
    So max_pages defaults to 1.
    """

    def __init__(
        self,
        category: str = "data",
        limit: int | None = None,
    ) -> None:
        self.category = category
        self.limit = limit

        super().__init__(
            source_name="remotive_api",
            base_url="https://remotive.com/api/remote-jobs",
            api_key="public",  # no api key required
            max_pages=1,  # one huge payload
            allow_empty=True,
        )

    def validate_source(self) -> bool:
        return True  # Public API

    def _build_request_params(self, page: int) -> dict[str, Any]:
        params: dict[str, Any] = {"category": self.category}
        if self.limit:
            params["limit"] = self.limit
        return params

    def _parse_response(self, response_json: dict[str, Any]) -> list[dict[str, Any]]:
        return response_json.get("jobs", [])
