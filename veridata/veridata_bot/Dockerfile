FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
# Install dependencies to /opt/venv to avoid volume mount shadowing
ENV UV_PROJECT_ENVIRONMENT="/opt/venv"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

FROM python:3.12-slim-bookworm
# Add /opt/venv/bin to PATH
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app
# Copy the environment from the builder stage
COPY --from=builder /opt/venv /opt/venv
COPY . .

# Ensure start script is executable
RUN chmod +x /app/start.sh

CMD ["/app/start.sh"]
