FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set working directory
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy project files
COPY pyproject.toml uv.lock ./

# Install dependencies
# We use --frozen to ensure exact versions from uv.lock are used
RUN uv sync --frozen --no-install-project

# Copy the rest of the application
COPY . .

# Place the virtualenv in the path
ENV PATH="/app/.venv/bin:$PATH"

# Run the application
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
