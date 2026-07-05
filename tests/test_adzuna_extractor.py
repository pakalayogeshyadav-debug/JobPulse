from unittest.mock import MagicMock, patch

from src.jobpulse.extraction.adzuna_extractor import AdzunaExtractor


def test_adzuna_extractor_init(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "test_id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test_key")
    extractor = AdzunaExtractor()
    assert extractor.app_id == "test_id"
    assert extractor.app_key == "test_key"
    assert extractor.country == "us"
    assert extractor.results_per_page == 50

def test_adzuna_extractor_validate_source_success():
    extractor = AdzunaExtractor(app_id="id", app_key="key")
    with patch("src.jobpulse.extraction.api_extractor.ApiExtractor.validate_source", return_value=True):
        assert extractor.validate_source() is True

def test_adzuna_extractor_validate_source_missing_creds():
    extractor = AdzunaExtractor(app_id=None, app_key=None)
    assert extractor.validate_source() is False
    
    extractor2 = AdzunaExtractor(app_id="id", app_key=None)
    assert extractor2.validate_source() is False

def test_adzuna_extractor_build_request_params():
    extractor = AdzunaExtractor(app_id="id", app_key="key", results_per_page=10)
    params = extractor._build_request_params(page=2)
    assert params["app_id"] == "id"
    assert params["app_key"] == "key"
    assert params["results_per_page"] == 10
    assert params["_page"] == 2

@patch("src.jobpulse.extraction.adzuna_extractor.AdzunaExtractor._get_session")
def test_adzuna_extractor_fetch_page_success(mock_get_session):
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": [{"id": 1}]}
    mock_session.get.return_value = mock_response
    mock_get_session.return_value = mock_session
    
    extractor = AdzunaExtractor(app_id="id", app_key="key")
    result = extractor._fetch_page({"_page": 2, "other": "val"})
    assert result == {"results": [{"id": 1}]}
    mock_session.get.assert_called_once_with(
        "https://api.adzuna.com/v1/api/jobs/us/search/2",
        params={"other": "val"},
        timeout=30.0
    )

@patch("src.jobpulse.extraction.adzuna_extractor.AdzunaExtractor._get_session")
def test_adzuna_extractor_fetch_page_request_exception(mock_get_session):
    mock_session = MagicMock()
    mock_session.get.side_effect = Exception("Network error")
    mock_get_session.return_value = mock_session
    
    extractor = AdzunaExtractor(app_id="id", app_key="key")
    try:
        extractor._fetch_page({"_page": 1})
        assert False
    except Exception as exc:
        assert "Request failed" in str(exc)

def test_adzuna_extractor_parse_response():
    extractor = AdzunaExtractor(app_id="id", app_key="key")
    result = extractor._parse_response({"results": [{"id": 1}, {"id": 2}]})
    assert len(result) == 2
    
    result_empty = extractor._parse_response({})
    assert result_empty == []
