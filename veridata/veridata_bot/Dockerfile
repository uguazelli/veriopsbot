FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
# Install dependencies to /opt/venv to avoid volume mount shadowing
ENV UV_PROJECT_ENVIRONMENT="/opt/venv"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

FROM python:3.13-slim-bookworm

# Create a non-root user
RUN groupadd -r veridata && useradd -r -g veridata veridata

# Add /opt/venv/bin to PATH
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app

# Copy the environment from the builder stage with correct ownership
COPY --from=builder --chown=veridata:veridata /opt/venv /opt/venv

# Copy application files with correct ownership
COPY --chown=veridata:veridata . .

# Ensure start script is executable
RUN chmod +x /app/start.sh

# Switch to non-root user
USER veridata

CMD ["/app/start.sh"]
