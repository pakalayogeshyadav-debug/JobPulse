# Developer Guide

Welcome to the JobPulse engineering team. This guide outlines how to set up your local environment and add new features.

## Local Setup

### 1. Prerequisites
- Python 3.12+
- Docker & Docker Compose
- Git

### 2. Virtual Environment
Clone the repo and set up your Python environment:
```bash
git clone https://github.com/<your-username>/jobpulse.git
cd jobpulse
python -m venv .venv

# Windows
.venv\Scripts\activate
# Mac/Linux
source .venv/bin/activate

# Install in editable mode with development dependencies
pip install -e ".[dev]"
```

### 3. Database Standup
Use Docker to spin up the local development database:
```bash
docker compose up -d postgres
```

### 4. Configuration
Create your local `.env` file:
```bash
cp .env.example .env
```
(No changes are required for local development if you use the defaults).

## Adding a New Data Source

To add a new API (e.g., LinkedIn, Greenhouse):

1. **Create an Extractor:**
   Create `src/jobpulse/extraction/my_new_api.py`. Inherit from `BaseExtractor` (or `ApiExtractor`) and implement the `extract()` method to return a Pandas DataFrame.
   
2. **Create a Transformer:**
   Create `src/jobpulse/transformation/my_new_api_transformer.py`. Map the raw API fields to the canonical JobPulse schema.

3. **Register the Source:**
   Update `data_sources` configuration in your Airflow DAG to include the new source. The pipeline will automatically dynamically generate the tasks for it.

## Testing

We use `pytest` for all tests. 
```bash
# Run all fast unit tests
pytest -m "not integration"

# Run integration tests (requires Docker PostgreSQL running)
pytest -m "integration"

# Generate coverage report
pytest --cov=src/jobpulse --cov-report=html
```

Open `htmlcov/index.html` to view test coverage.
