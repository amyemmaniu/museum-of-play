"""PostgreSQL connection pool and the per-request connection dependency.

A pool keeps a few database connections open and lends one to each request, which is much
faster than connecting to Postgres from scratch every time an endpoint is called.
"""

import os
from collections.abc import Iterator
from pathlib import Path

from dotenv import load_dotenv
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# Load backend/.env into environment variables, e.g.
# DATABASE_URL=postgresql://user:password@localhost:5432/museum_of_play
# The path is built from this file's location, so it works no matter where the server is started.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# The pool is created at startup (see main.py's lifespan), not when this module is imported,
# so importing the app never tries to reach the database.
_pool: ConnectionPool | None = None

def open_pool() -> None:
    """Open the connection pool. Called once when the app starts."""
    global _pool
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Add it to backend/.env.")
    # Rows come back as dicts keyed by column name, which map directly onto the Pydantic models.
    _pool = ConnectionPool(
        conninfo=database_url,
        kwargs={"row_factory": dict_row},
        open=False,
    )
    # wait=True blocks until a connection succeeds, so bad credentials fail at startup.
    _pool.open(wait=True)

def close_pool() -> None:
    """Close the connection pool. Called once when the app shuts down."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None

def get_db() -> Iterator[Connection]:
    """FastAPI dependency that lends a connection to one request.

    Endpoints receive it by declaring a `conn` parameter with `Depends(get_db)`.
    The transaction commits if the request succeeds and rolls back if it raises,
    so a request that fails halfway never leaves partial changes in the database.
    """
    if _pool is None:
        raise RuntimeError("Connection pool is not open.")
    with _pool.connection() as conn:
        yield conn
