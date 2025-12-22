FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
# Using pip to install from pyproject.toml (conceptually similar to uv/poetry export requirements,
# but for simplicity we can just pip install . if we struct it right, or just install manually since we listed them)
# To keep it simple and standard without requiring uv inside container yet:
COPY pyproject.toml .
# We don't have a lock file yet, so we'll install dependencies directly based on pyproject.toml
# Since pip doesn't read standard pyproject.toml dependencies directly without a build backend sometimes,
# I will create a requirements.txt on the fly or just install the list.
# Actually, pip install . works if we have a minimal setup, but let's just use a requirements file approach or manual install for robustness unless we commit to uv.
# Let's use standard pip install of packages for now to avoid complexity of build tools inside image.
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" asyncpg sqladmin pydantic-settings httpx python-multipart psycopg2-binary alembic requests

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
