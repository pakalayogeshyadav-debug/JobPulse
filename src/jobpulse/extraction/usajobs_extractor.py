"""jobpulse.extraction.usajobs_extractor — USAJobs REST API extractor."""

from __future__ import annotations

import os
from typing import Any

from jobpulse.extraction.api_extractor import ApiExtractor


class UsaJobsExtractor(ApiExtractor):
    """Extracts federal job listings from the USAJobs API."""

    def __init__(
        self,
        api_key: str | None = None,
        user_agent: str | None = None,
        keyword: str = "data",
        results_per_page: int = 500,
        max_pages: int = 10,
    ) -> None:
        self.user_agent = user_agent or os.getenv(
            "USAJOBS_USER_AGENT", "jobpulse_bot@example.com"
        )
        self.api_key = api_key or os.getenv("USAJOBS_API_KEY") or ""
        self.keyword = keyword
        self.results_per_page = results_per_page

        super().__init__(
            source_name="usajobs_api",
            base_url="https://data.usajobs.gov/api/search",
            api_key=self.api_key,
            max_pages=max_pages,
            request_delay_seconds=1.0,
            allow_empty=True,
        )

    def _get_session(self) -> Any:
        session = super()._get_session()
        session.headers.update(
            {
                "Host": "data.usajobs.gov",
                "User-Agent": str(self.user_agent),
                "Authorization-Key": str(self.api_key),
            }
        )
        return session

    def _build_request_params(self, page: int) -> dict[str, Any]:
        return {
            "Keyword": self.keyword,
            "ResultsPerPage": self.results_per_page,
            "Page": page,
        }

    def _parse_response(self, response_json: dict[str, Any]) -> list[dict[str, Any]]:
        search_result = response_json.get("SearchResult", {})
        search_result_items = search_result.get("SearchResultItems", [])

        # Flatten the nested structure slightly for pandas
        parsed_items = []
        for item in search_result_items:
            job = item.get("MatchedObjectDescriptor", {})
            parsed_items.append(job)

        return parsed_items
