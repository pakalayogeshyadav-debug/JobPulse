"""
tests — JobPulse pytest test suite.

Test Organisation:
    tests/
    ├── conftest.py                  → Shared fixtures (session, sample data)
    ├── test_config.py               → Tests for settings and yaml loader
    ├── test_extraction.py           → Tests for extractor modules
    ├── test_transformation.py       → Tests for transformer modules
    ├── test_loading.py              → Tests for loader modules
    ├── test_validation.py           → Tests for validator modules
    └── test_utils/
        ├── test_file_utils.py       → Tests for file utilities
        ├── test_string_utils.py     → Tests for string utilities
        └── test_date_utils.py       → Tests for date utilities

Test Markers (defined in pyproject.toml):
    @pytest.mark.unit         → Fast, no DB/network required
    @pytest.mark.integration  → Requires live PostgreSQL connection
    @pytest.mark.slow         → Takes > 5 seconds

Running Tests:
    pytest                    → All tests
    pytest -m unit            → Unit tests only
    pytest -m "not integration" → Skip integration tests
    pytest --cov              → With coverage report
"""
