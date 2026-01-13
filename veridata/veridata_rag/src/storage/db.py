import os
import logging
from contextlib import contextmanager
from typing import Generator
import psycopg
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

# Singleton pool
_pool: ConnectionPool = None

def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise ValueError("DATABASE_URL environment variable is not set")
        _pool = ConnectionPool(conninfo=db_url, min_size=1, max_size=10)
    return _pool

@contextmanager
def get_db() -> Generator[psycopg.Connection, None, None]:
    pool = get_pool()
    with pool.connection() as conn:
        yield conn



def close_pool():
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
