import pytest
from src.jobpulse.extraction.csv_extractor import CsvExtractor
from src.jobpulse.extraction.directory_extractor import DirectoryExtractor


def test_csv_extractor_valid(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text("title,company\njob1,acme\njob2,beta\n")

    ext = CsvExtractor(file_path=f)
    df = ext.extract()
    assert len(df) == 2
    assert "title" in df.columns
    assert "company" in df.columns


def test_csv_extractor_empty(tmp_path):
    f = tmp_path / "empty.csv"
    f.write_text("title,company\n")

    ext = CsvExtractor(file_path=f, allow_empty=True)
    df = ext.extract()
    assert len(df) == 0


def test_csv_extractor_invalid_path():
    ext = CsvExtractor(file_path="nonexistent.csv")
    assert ext.validate_source() is False


def test_csv_extractor_chunking(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text("title,company\njob1,acme\njob2,beta\n")

    ext = CsvExtractor(file_path=f, chunk_size=1)
    chunks = list(ext.extract_chunks())
    assert len(chunks) == 2
    assert len(chunks[0]) == 1


def test_directory_extractor_valid(tmp_path):
    d = tmp_path / "data"
    d.mkdir()

    f1 = d / "1.csv"
    f1.write_text("title,company\njob1,acme\n")

    f2 = d / "2.csv"
    f2.write_text("title,company\njob2,beta\n")

    ext = DirectoryExtractor(directory=d)
    assert ext.validate_source() is True

    df = ext.extract()
    assert len(df) == 2
    assert "_source_file" in df.columns


def test_directory_extractor_strict(tmp_path):
    d = tmp_path / "data"
    d.mkdir()

    f1 = d / "1.csv"
    f1.write_text("title,company\njob1,acme\n")

    f2 = d / "2.csv"
    f2.write_text("title,location\njob2,remote\n")

    ext = DirectoryExtractor(directory=d, schema_mode="strict")
    with pytest.raises(Exception):
        ext.extract()


def test_directory_extractor_intersect(tmp_path):
    d = tmp_path / "data"
    d.mkdir()

    f1 = d / "1.csv"
    f1.write_text("title,company\njob1,acme\n")

    f2 = d / "2.csv"
    f2.write_text("title,location\njob2,remote\n")

    ext = DirectoryExtractor(directory=d, schema_mode="intersect")
    df = ext.extract()
    assert len(df) == 2
    assert "title" in df.columns
    assert "company" not in df.columns
    assert "location" not in df.columns


def test_directory_extractor_invalid_dir():
    ext = DirectoryExtractor(directory="nonexistent")
    assert ext.validate_source() is False
