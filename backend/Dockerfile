FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system dependencies needed by psycopg2/bcrypt/cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first — maximises Docker layer cache hits.
# pip install only reruns when requirements.txt changes, not on every code change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source and migration files
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini .
COPY scripts/ scripts/
COPY data/ data/

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

EXPOSE 8000

# WEB_CONCURRENCY is read from env (default 1 for dev, set higher in prod via .env)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-1}"]
