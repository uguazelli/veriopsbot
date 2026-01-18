FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy the dependency definition
COPY pyproject.toml .
COPY uv.lock .

# Install dependencies
RUN uv sync --frozen --no-install-project

FROM python:3.13-slim-bookworm
# Create a non-root user
RUN groupadd -r veridata && useradd -r -g veridata veridata

WORKDIR /app

# Copy the environment from the builder
COPY --from=builder --chown=veridata:veridata /app/.venv /app/.venv

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Copy the application code
COPY --chown=veridata:veridata . .

# Switch to non-root user
USER veridata

# Run the application
CMD ["sh", "-c", "python -m app.scripts.pre_start && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
