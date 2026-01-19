#!/bin/bash
set -e

# Run migrations if you have them, e.g.
# alembic upgrade head

# Wait for DB
python -m app.scripts.pre_start

# Start the application
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
