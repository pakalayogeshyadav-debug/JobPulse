from unittest.mock import MagicMock, patch

import requests
from src.jobpulse.extraction.api_extractor import ApiExtractor


class DummyApiExtractor(ApiExtractor):
    def _build_request_params(self, page: int):
        return {"page": page}

    def _parse_response(self, response_json):
        return response_json.get("items", [])


def test_api_extractor_init():
    extractor = DummyApiExtractor(
        source_name="dummy",
        base_url="http://dummy",
        api_key="secret",
        max_pages=2,
        timeout_seconds=10,
        max_retries=1,
        request_delay_seconds=0.0,
    )
    assert extractor.source_name == "dummy"
    assert extractor.base_url == "http://dummy"
    assert extractor.api_key == "secret"
    assert extractor.max_pages == 2


def test_api_extractor_validate_source():
    extractor = DummyApiExtractor("dummy", "http://dummy", "secret")
    assert extractor.validate_source() is True

    extractor2 = DummyApiExtractor("dummy", "", "secret")
    assert extractor2.validate_source() is False

    extractor3 = DummyApiExtractor("dummy", "http://dummy", "")
    assert extractor3.validate_source() is False


def test_api_extractor_get_session():
    extractor = DummyApiExtractor("dummy", "http://dummy", "secret")
    session = extractor._get_session()
    assert session is not None
    assert session is extractor._session
    assert session.headers.get("User-Agent") == "JobPulse-ETL/1.0 (github.com/jobpulse)"


def test_api_extractor_close():
    extractor = DummyApiExtractor("dummy", "http://dummy", "secret")
    extractor._get_session()
    extractor.close()
    assert extractor._session is None
    # Context manager
    with DummyApiExtractor("dummy", "http://dummy", "secret") as ext:
        ext._get_session()
    assert ext._session is None


@patch("src.jobpulse.extraction.api_extractor.ApiExtractor._get_session")
def test_api_extractor_fetch_page_success(mock_get_session):
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"items": [{"id": 1}]}
    mock_session.get.return_value = mock_response
    mock_get_session.return_value = mock_session

    extractor = DummyApiExtractor("dummy", "http://dummy", "secret")
    res = extractor._fetch_page({"page": 1})
    assert res == {"items": [{"id": 1}]}


@patch("src.jobpulse.extraction.api_extractor.ApiExtractor._get_session")
def test_api_extractor_fetch_page_timeout(mock_get_session):
    mock_session = MagicMock()
    mock_session.get.side_effect = requests.exceptions.Timeout("timeout")
    mock_get_session.return_value = mock_session

    extractor = DummyApiExtractor("dummy", "http://dummy", "secret")
    try:
        extractor._fetch_page({"page": 1})
        assert False
    except Exception as exc:
        assert "Request timed out" in str(exc)


@patch("src.jobpulse.extraction.api_extractor.ApiExtractor._get_session")
def test_api_extractor_fetch_page_connection_error(mock_get_session):
    mock_session = MagicMock()
    mock_session.get.side_effect = requests.exceptions.ConnectionError("conn_err")
    mock_get_session.return_value = mock_session

    extractor = DummyApiExtractor("dummy", "http://dummy", "secret")
    try:
        extractor._fetch_page({"page": 1})
        assert False
    except Exception as exc:
        assert "Connection error" in str(exc)


@patch("src.jobpulse.extraction.api_extractor.ApiExtractor._get_session")
def test_api_extractor_fetch_page_request_error(mock_get_session):
    mock_session = MagicMock()
    mock_session.get.side_effect = requests.exceptions.RequestException("req_err")
    mock_get_session.return_value = mock_session

    extractor = DummyApiExtractor("dummy", "http://dummy", "secret")
    try:
        extractor._fetch_page({"page": 1})
        assert False
    except Exception as exc:
        assert "HTTP request failed" in str(exc)


def test_api_extractor_validate_response_status():
    extractor = DummyApiExtractor("dummy", "http://dummy", "secret")
    mock_response = MagicMock()

    mock_response.status_code = 200
    extractor._validate_response_status(mock_response)  # should not raise

    status_codes = [
        (401, "Unauthorized"),
        (403, "Forbidden"),
        (404, "Not Found"),
        (429, "Too Many Requests"),
        (500, "Server Error"),
        (502, "Server Error"),
        (418, "Unexpected HTTP 418"),
    ]
    for code, msg in status_codes:
        mock_response.status_code = code
        try:
            extractor._validate_response_status(mock_response)
            assert False, f"Should have raised for status {code}"
        except Exception as exc:
            assert msg in str(exc)


def test_api_extractor_parse_json_body():
    extractor = DummyApiExtractor("dummy", "http://dummy", "secret")
    mock_response = MagicMock()
    mock_response.json.return_value = {"a": 1}
    assert extractor._parse_json_body(mock_response) == {"a": 1}

    mock_response.json.side_effect = ValueError("bad json")
    try:
        extractor._parse_json_body(mock_response)
        assert False
    except Exception as exc:
        assert "not valid JSON" in str(exc)


@patch("src.jobpulse.extraction.api_extractor.ApiExtractor._fetch_page")
def test_api_extractor_extract_success(mock_fetch_page):
    # Mock to return data for page 1, empty for page 2
    mock_fetch_page.side_effect = [{"items": [{"id": 1}]}, {"items": []}]

    extractor = DummyApiExtractor(
        "dummy", "http://dummy", "secret", max_pages=3, request_delay_seconds=0.0
    )
    df = extractor.extract()
    assert len(df) == 1
    assert extractor._total_pages_fetched == 1
    assert mock_fetch_page.call_count == 2


@patch("src.jobpulse.extraction.api_extractor.ApiExtractor._fetch_page")
def test_api_extractor_extract_max_pages(mock_fetch_page):
    # Mock to always return data
    mock_fetch_page.return_value = {"items": [{"id": 1}]}

    extractor = DummyApiExtractor(
        "dummy", "http://dummy", "secret", max_pages=2, request_delay_seconds=0.0
    )
    df = extractor.extract()
    assert len(df) == 2
    assert extractor._total_pages_fetched == 2
    assert mock_fetch_page.call_count == 2


def test_api_extractor_repr():
    extractor = DummyApiExtractor("dummy", "http://dummy", "secret")
    rep = repr(extractor)
    assert "DummyApiExtractor" in rep
    assert "'dummy'" in rep


def test_api_extractor_build_extra_metadata():
    extractor = DummyApiExtractor("dummy", "http://dummy", "secret", max_pages=5)
    meta = extractor._build_extra_metadata()
    assert meta["base_url"] == "http://dummy"
    assert meta["pages_fetched"] == 0
    assert meta["max_pages"] == 5
