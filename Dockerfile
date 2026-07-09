# =============================================================================
# Stage 1: Builder
# =============================================================================
FROM python:3.12-slim AS builder

# Prevent Python from writing pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies (often needed for compiling Python packages)
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Create a virtual environment and install dependencies
# We build wheels and install them into the venv to keep the final image clean
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# =============================================================================
# Stage 2: Runtime
# =============================================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install runtime dependencies (like libpq5 for PostgreSQL client)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 && \
    rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN groupadd -r jobpulse && useradd -r -g jobpulse jobpulse

WORKDIR /app

# Copy the virtual environment from the builder stage
COPY --from=builder --chown=jobpulse:jobpulse /opt/venv /opt/venv

# Ensure the virtual environment is used
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code and ensure ownership belongs to the non-root user
COPY --chown=jobpulse:jobpulse src/ ./src/
COPY --chown=jobpulse:jobpulse main.py ./

# Create directories for logs, data, and reports so they exist with correct permissions
RUN mkdir -p logs data reports && chown -R jobpulse:jobpulse logs data reports

# Ensure Python can find the src module
ENV PYTHONPATH="/app/src"

# Switch to the non-root user
USER jobpulse

# Default command to run the pipeline orchestrator
CMD ["python", "main.py"]
