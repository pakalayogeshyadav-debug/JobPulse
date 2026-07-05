import json

from src.jobpulse.extraction.json_extractor import JsonExtractor


def test_json_extractor_validate_source_exists(tmp_path):
    file_path = tmp_path / "test.json"
    file_path.write_text("[]", encoding="utf-8")
    extractor = JsonExtractor(file_path)
    assert extractor.validate_source() is True

def test_json_extractor_validate_source_not_exists(tmp_path):
    file_path = tmp_path / "non_existent.json"
    extractor = JsonExtractor(file_path)
    assert extractor.validate_source() is False

def test_json_extractor_validate_source_is_dir(tmp_path):
    extractor = JsonExtractor(tmp_path)
    assert extractor.validate_source() is False

def test_json_extractor_extract_list(tmp_path):
    file_path = tmp_path / "test.json"
    file_path.write_text(json.dumps([{"id": 1, "title": "A"}]), encoding="utf-8")
    extractor = JsonExtractor(file_path)
    df = extractor.extract()
    assert len(df) == 1
    assert df.iloc[0]["id"] == "1" # Should be converted to str

def test_json_extractor_extract_dict_jobs(tmp_path):
    file_path = tmp_path / "test.json"
    file_path.write_text(json.dumps({"jobs": [{"id": 1}]}), encoding="utf-8")
    extractor = JsonExtractor(file_path)
    df = extractor.extract()
    assert len(df) == 1

def test_json_extractor_extract_dict_results(tmp_path):
    file_path = tmp_path / "test.json"
    file_path.write_text(json.dumps({"results": [{"id": 1}]}), encoding="utf-8")
    extractor = JsonExtractor(file_path)
    df = extractor.extract()
    assert len(df) == 1

def test_json_extractor_extract_dict_data(tmp_path):
    file_path = tmp_path / "test.json"
    file_path.write_text(json.dumps({"data": [{"id": 1}]}), encoding="utf-8")
    extractor = JsonExtractor(file_path)
    df = extractor.extract()
    assert len(df) == 1

def test_json_extractor_extract_dict_flatten(tmp_path):
    file_path = tmp_path / "test.json"
    file_path.write_text(json.dumps({"id": 1, "title": "B"}), encoding="utf-8")
    extractor = JsonExtractor(file_path)
    df = extractor.extract()
    assert len(df) == 1
    assert df.iloc[0]["title"] == "B"

def test_json_extractor_extract_invalid_structure(tmp_path):
    file_path = tmp_path / "test.json"
    file_path.write_text(json.dumps(123), encoding="utf-8") # not dict or list
    extractor = JsonExtractor(file_path)
    try:
        extractor.extract()
        assert False, "Should have raised DataExtractionError"
    except Exception as exc:
        assert "JSON file does not contain a recognizable list" in str(exc)

def test_json_extractor_extract_invalid_json(tmp_path):
    file_path = tmp_path / "test.json"
    file_path.write_text("{bad_json", encoding="utf-8")
    extractor = JsonExtractor(file_path)
    try:
        extractor.extract()
        assert False, "Should have raised DataExtractionError"
    except Exception as exc:
        assert "Failed to parse JSON file" in str(exc)

def test_json_extractor_extract_general_error(tmp_path):
    file_path = tmp_path / "test.json"
    extractor = JsonExtractor(file_path)
    try:
        extractor.extract() # file doesn't exist, causes FileNotFoundError
        assert False, "Should have raised DataExtractionError"
    except Exception as exc:
        assert "No such file or directory" in str(exc)
