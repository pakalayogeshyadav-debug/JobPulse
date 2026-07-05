import json

from src.jobpulse.extraction.adzuna_extractor import AdzunaExtractor
from src.jobpulse.extraction.arbeitnow_extractor import ArbeitnowExtractor
from src.jobpulse.extraction.greenhouse_extractor import GreenhouseExtractor
from src.jobpulse.extraction.json_extractor import JsonExtractor
from src.jobpulse.extraction.lever_extractor import LeverExtractor
from src.jobpulse.extraction.remotive_extractor import RemotiveExtractor
from src.jobpulse.extraction.usajobs_extractor import UsaJobsExtractor


def test_adzuna_extractor():
    ext = AdzunaExtractor(app_id="id", app_key="k")
    params = ext._build_request_params(1)
    assert params["app_id"] == "id"
    assert params["app_key"] == "k"
    
    res = ext._parse_response({"results": [{"title": "t"}]})
    assert len(res) == 1

def test_arbeitnow_extractor():
    ext = ArbeitnowExtractor()
    params = ext._build_request_params(1)
    assert params["page"] == 1
    
    res = ext._parse_response({"data": [{"title": "t"}]})
    assert len(res) == 1

def test_greenhouse_extractor():
    ext = GreenhouseExtractor(board_token="tok")
    res = ext._parse_response({"jobs": [{"title": "t"}]})
    assert len(res) == 1

def test_lever_extractor():
    ext = LeverExtractor(company_name="test")
    res = ext._parse_response([{"title": "t"}])
    assert len(res) == 1

def test_remotive_extractor():
    ext = RemotiveExtractor()
    res = ext._parse_response({"jobs": [{"title": "t"}]})
    assert len(res) == 1

def test_usajobs_extractor():
    ext = UsaJobsExtractor(api_key="k", user_agent="e")
    params = ext._build_request_params(1)
    assert params["Page"] == 1
    
    res = ext._parse_response({"SearchResult": {"SearchResultItems": [{"title": "t"}]}})
    assert len(res) == 1

def test_json_extractor(tmp_path):
    f = tmp_path / "test.json"
    f.write_text(json.dumps([{"title": "t1"}]))
    
    ext = JsonExtractor(file_path=f)
    df = ext.extract()
    assert len(df) == 1
    assert "title" in df.columns
