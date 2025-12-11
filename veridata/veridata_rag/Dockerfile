FROM python:3.12-slim-bookworm

# Install uv from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
# --frozen ensures we use the exact versions from uv.lock
# --no-dev to skip dev dependencies if any
RUN uv sync --frozen --no-dev

# Copy source code
COPY src/ ./src/

# Expose the application port
EXPOSE 8000

# Run the application
# We use `uv run` to ensure the environment matches the one created by `uv sync`
CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
