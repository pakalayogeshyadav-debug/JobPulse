"""jobpulse.extraction.api_extractor — Production REST API extractor base class.

Provides a complete, production-ready foundation for all API-based extractors.
Handles the concerns common to every REST API source:
    - HTTP session management (requests.Session with retry adapter)
    - Exponential-backoff retry logic via urllib3.util.Retry
    - Configurable timeout
    - Paginated response iteration
    - Request rate limiting (minimum delay between consecutive requests)
    - Response validation (status code, JSON structure)
    - Circuit-breaker via max_pages limit

Concrete subclasses implement only two methods:
    _build_request_params(page)   — Return query parameters for page N
    _parse_response(response_json) — Extract job records from the JSON body

This class is NOT abstract — it can be tested directly with a mock server.
But in practice, callers always instantiate a concrete subclass.

Class Hierarchy:
    BaseExtractor  (abstract)
        └── ApiExtractor  (this file — semi-abstract)
                ├── AdzunaExtractor     (future: src/extraction/adzuna.py)
                └── UsaJobsExtractor    (future: src/extraction/usajobs.py)

Usage (via subclass):
    >>> class MyApiExtractor(ApiExtractor):
    ...     def _build_request_params(self, page: int) -> dict:
    ...         return {"page": page, "key": self.api_key}
    ...
    ...     def _parse_response(self, data: dict) -> list[dict]:
    ...         return data.get("results", [])
    ...
    >>> extractor = MyApiExtractor(
    ...     source_name="my_api",
    ...     base_url="https://api.example.com/jobs",
    ...     api_key="secret",
    ...     max_pages=5,
    ... )
    >>> df, meta = extractor.run()
"""

from __future__ import annotations

import time
from abc import abstractmethod
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from jobpulse.extraction.base import (
    BaseExtractor,
    DataExtractionError,
)


class ApiExtractor(BaseExtractor):
    """Abstract base class for all REST API-based extractors.

    Manages a persistent requests.Session with automatic retry logic,
    and provides a paginated extraction loop that concrete subclasses
    hook into by implementing _build_request_params() and _parse_response().

    Retry Behaviour:
        Failed requests are automatically retried up to max_retries times
        with exponential backoff. Only transient server-side errors trigger
        retries (status codes: 429, 500, 502, 503, 504).
        Client errors (4xx except 429) are NOT retried.

    Rate Limiting:
        A configurable delay (request_delay_seconds) is enforced between
        consecutive HTTP requests to respect source API rate limits.

    Attributes:
        base_url:              Root endpoint URL for the API.
        api_key:               Primary authentication key/token.
        max_pages:             Maximum pages to fetch (circuit breaker).
        timeout_seconds:       Per-request timeout in seconds.
        max_retries:           Maximum retry attempts per request.
        request_delay_seconds: Minimum seconds between consecutive requests.
        _session:              Persistent requests.Session (created lazily).
    """

    # HTTP status codes that should trigger an automatic retry
    _RETRY_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        source_name: str,
        base_url: str,
        api_key: str,
        max_pages: int = 10,
        timeout_seconds: int = 30,
        max_retries: int = 3,
        request_delay_seconds: float = 0.5,
        allow_empty: bool = False,
    ) -> None:
        """Initialise the API extractor.

        Args:
            source_name:            Machine-readable identifier (e.g., 'adzuna').
            base_url:               Root URL for all API requests.
            api_key:                API authentication key or Bearer token.
            max_pages:              Maximum number of pages to fetch.
                                    Acts as a circuit breaker. Default: 10.
            timeout_seconds:        Per-request timeout. Default: 30 seconds.
            max_retries:            Retry attempts for transient failures.
                                    Default: 3.
            request_delay_seconds:  Pause between requests (rate limiting).
                                    Default: 0.5 seconds.
            allow_empty:            Whether 0 rows is a valid result.
                                    Default: False.
        """
        super().__init__(source_name=source_name, allow_empty=allow_empty)
        self.base_url: str = base_url.rstrip("/")
        self.api_key: str = api_key
        self.max_pages: int = max_pages
        self.timeout_seconds: int = timeout_seconds
        self.max_retries: int = max_retries
        self.request_delay_seconds: float = request_delay_seconds

        # Session is created lazily on first use (avoids opening connections
        # during __init__ before the network is needed)
        self._session: requests.Session | None = None
        self._total_pages_fetched: int = 0

    # ─────────────────────────────────────────────────────────────────────────
    # Abstract methods — subclasses MUST implement these
    # ─────────────────────────────────────────────────────────────────────────

    @abstractmethod
    def _build_request_params(self, page: int) -> dict[str, Any]:
        """Build the query parameter dictionary for a given page number.

        Called once per page in the extraction loop.

        Args:
            page: 1-indexed page number to fetch.

        Returns:
            dict[str, Any]: Query parameters to pass to requests.get(params=...).

        Example:
            >>> def _build_request_params(self, page: int) -> dict:
            ...     return {
            ...         "app_id":  self.api_key_id,
            ...         "app_key": self.api_key,
            ...         "page":    page,
            ...         "results_per_page": 50,
            ...     }
        """
        ...

    @abstractmethod
    def _parse_response(self, response_json: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract the list of job record dicts from a raw API response body.

        Called once per page with the parsed JSON body.

        Args:
            response_json: The full parsed JSON response from the API.

        Returns:
            list[dict[str, Any]]: Flat list of job record dictionaries.
                                  Return an empty list [] when there are no
                                  more results (signals pagination to stop).

        Example:
            >>> def _parse_response(self, data: dict) -> list[dict]:
            ...     return data.get("results", [])
        """
        ...

    # ─────────────────────────────────────────────────────────────────────────
    # BaseExtractor interface implementation
    # ─────────────────────────────────────────────────────────────────────────

    def validate_source(self) -> bool:
        """Validate that required credentials are present and the URL is set.

        Checks:
            1. base_url is a non-empty string.
            2. api_key is a non-empty string.

        Note:
            Does NOT make a live network request — subclasses that need a
            live health check should override this method and call
            ``super().validate_source()`` first.

        Returns:
            bool: True if credentials are configured.
        """
        if not self.base_url:
            self._logger.warning(
                "Validation failed for '%s': base_url is not set.",
                self.source_name,
            )
            return False

        if not self.api_key:
            self._logger.warning(
                "Validation failed for '%s': api_key is not set.",
                self.source_name,
            )
            return False

        self._logger.debug(
            "API validation passed for '%s' (credentials present).",
            self.source_name,
        )
        return True

    def extract(self) -> pd.DataFrame:
        """Fetch all pages from the API and return as a single DataFrame.

        Iterates from page 1 to max_pages, stopping early when:
            - _parse_response() returns an empty list (no more data)
            - max_pages is reached (circuit breaker)

        Returns:
            pd.DataFrame: Combined records from all fetched pages.

        Raises:
            DataExtractionError: If any page fetch fails after all retries.

        Example:
            >>> df = extractor.extract()
            >>> print(f"Loaded {len(df)} job records from {extractor._total_pages_fetched} pages")
        """
        all_records: list[dict[str, Any]] = []
        self._total_pages_fetched = 0

        for page in range(1, self.max_pages + 1):
            self._logger.info(
                "Fetching page %d/%d from '%s'",
                page,
                self.max_pages,
                self.source_name,
            )

            params = self._build_request_params(page)
            response_json = self._fetch_page(params)
            records = self._parse_response(response_json)

            if not records:
                self._logger.info(
                    "Page %d returned 0 records — pagination complete for '%s'.",
                    page,
                    self.source_name,
                )
                break

            all_records.extend(records)
            self._total_pages_fetched = page

            self._logger.debug(
                "Page %d: +%d records (total so far: %d)",
                page,
                len(records),
                len(all_records),
            )

            # Rate-limit delay between requests
            if page < self.max_pages and self.request_delay_seconds > 0:
                time.sleep(self.request_delay_seconds)

        else:
            # Loop exhausted max_pages without seeing an empty page
            self._logger.warning(
                "Reached max_pages limit (%d) for '%s'. "
                "There may be more data. Increase max_pages if needed.",
                self.max_pages,
                self.source_name,
            )

        self._logger.info(
            "API extraction complete: %d records from %d page(s) | source='%s'",
            len(all_records),
            self._total_pages_fetched,
            self.source_name,
        )
        return pd.DataFrame(all_records)

    # ─────────────────────────────────────────────────────────────────────────
    # HTTP internals
    # ─────────────────────────────────────────────────────────────────────────

    def _get_session(self) -> requests.Session:
        """Return the shared requests.Session, creating it on first call.

        The session is configured with:
            - Automatic retries with exponential backoff
            - Retry only on transient server errors (429, 5xx)
            - User-Agent header identifying the JobPulse pipeline

        Returns:
            requests.Session: Configured session with retry adapter mounted.
        """
        if self._session is None:
            retry_strategy = Retry(
                total=self.max_retries,
                backoff_factor=1.0,  # Wait: 1s, 2s, 4s between retries
                status_forcelist=list(self._RETRY_STATUS_CODES),
                allowed_methods=["GET"],
                raise_on_status=False,  # We raise ourselves after inspection
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session = requests.Session()
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            session.headers.update(
                {
                    "User-Agent": "JobPulse-ETL/1.0 (github.com/jobpulse)",
                    "Accept": "application/json",
                }
            )
            self._session = session
            self._logger.debug(
                "HTTP session created for '%s' (max_retries=%d)",
                self.source_name,
                self.max_retries,
            )
        return self._session

    def _fetch_page(self, params: dict[str, Any]) -> dict[str, Any]:
        """Make an HTTP GET request for one page and return the parsed JSON body.

        Args:
            params: Query parameters to include in the GET request.

        Returns:
            dict[str, Any]: Parsed JSON response body.

        Raises:
            DataExtractionError: On network error, HTTP error, or JSON parse error.
        """
        session = self._get_session()

        try:
            response = session.get(
                self.base_url,
                params=params,
                timeout=self.timeout_seconds,
            )
        except requests.exceptions.Timeout as exc:
            raise DataExtractionError(
                source_name=self.source_name,
                message=(
                    f"Request timed out after {self.timeout_seconds}s "
                    f"for URL: {self.base_url}"
                ),
                cause=exc,
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise DataExtractionError(
                source_name=self.source_name,
                message=(
                    f"Connection error for URL: {self.base_url}. "
                    "Check network connectivity and the base_url."
                ),
                cause=exc,
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise DataExtractionError(
                source_name=self.source_name,
                message=f"HTTP request failed: {exc}",
                cause=exc,
            ) from exc

        # Inspect the HTTP status code
        self._validate_response_status(response)

        # Parse the JSON body
        return self._parse_json_body(response)

    def _validate_response_status(self, response: requests.Response) -> None:
        """Raise DataExtractionError if the HTTP response indicates failure.

        Args:
            response: The HTTP response object.

        Raises:
            DataExtractionError: For 4xx (except 429, which retries) and 5xx.
        """
        if response.status_code == 200:
            return

        if response.status_code == 401:
            raise DataExtractionError(
                source_name=self.source_name,
                message=(
                    "HTTP 401 Unauthorized: API key is invalid or expired. "
                    "Check your API key credentials in .env."
                ),
            )
        if response.status_code == 403:
            raise DataExtractionError(
                source_name=self.source_name,
                message=(
                    "HTTP 403 Forbidden: Access denied. "
                    "Check API permissions and subscription tier."
                ),
            )
        if response.status_code == 404:
            raise DataExtractionError(
                source_name=self.source_name,
                message=f"HTTP 404 Not Found: URL does not exist: {response.url}",
            )
        if response.status_code == 429:
            raise DataExtractionError(
                source_name=self.source_name,
                message=(
                    "HTTP 429 Too Many Requests: Rate limit exceeded. "
                    "Increase request_delay_seconds or reduce max_pages."
                ),
            )
        if response.status_code >= 500:
            raise DataExtractionError(
                source_name=self.source_name,
                message=(
                    f"HTTP {response.status_code} Server Error from "
                    f"'{self.base_url}'. The API may be temporarily unavailable."
                ),
            )

        # Any other non-200 status
        raise DataExtractionError(
            source_name=self.source_name,
            message=(
                f"Unexpected HTTP {response.status_code} from '{response.url}'. "
                f"Response body (truncated): {response.text[:200]}"
            ),
        )

    def _parse_json_body(self, response: requests.Response) -> dict[str, Any]:
        """Parse the HTTP response body as JSON.

        Args:
            response: A successful (2xx) HTTP response.

        Returns:
            dict[str, Any]: Parsed JSON body.

        Raises:
            DataExtractionError: If the body is not valid JSON.
        """
        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            raise DataExtractionError(
                source_name=self.source_name,
                message=(
                    f"Response from '{response.url}' is not valid JSON. "
                    f"Content-Type: {response.headers.get('Content-Type')}. "
                    f"Body preview: {response.text[:200]!r}"
                ),
                cause=exc,
            ) from exc
        return data

    def close(self) -> None:
        """Close the underlying HTTP session and release network resources.

        Call this when the extractor is no longer needed.
        Not required when used as a context manager (see __enter__/__exit__).
        """
        if self._session is not None:
            self._session.close()
            self._session = None
            self._logger.debug("HTTP session closed for '%s'.", self.source_name)

    def __enter__(self) -> ApiExtractor:
        """Support context manager usage: ``with ApiExtractor(...) as ext:``."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Close the HTTP session on context manager exit."""
        self.close()

    def _build_extra_metadata(self) -> dict[str, Any]:
        """Include API-specific metadata in the extraction record."""
        return {
            "base_url": self.base_url,
            "pages_fetched": self._total_pages_fetched,
            "max_pages": self.max_pages,
        }

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"source={self.source_name!r}, "
            f"url={self.base_url!r}, "
            f"max_pages={self.max_pages!r})"
        )
