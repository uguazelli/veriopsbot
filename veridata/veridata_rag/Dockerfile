FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

FROM python:3.13-slim-bookworm

# Create a non-root user
RUN groupadd -r veridata && useradd -r -g veridata veridata

ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# Copy the environment with ownership
COPY --from=builder --chown=veridata:veridata /app/.venv /app/.venv

# Copy source code with ownership
COPY --chown=veridata:veridata src/ ./src/
COPY --chown=veridata:veridata alembic.ini .
COPY --chown=veridata:veridata migrations/ ./migrations/

EXPOSE 8000

# Switch to non-root user
USER veridata

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
