"""PostgreSQL connection pool and the per-request connection dependency.

WHAT THIS FILE DOES
It manages the API's connection to the PostgreSQL database.

A "connection pool" keeps a few database connections open and lends one to each request.
That is much faster than connecting to Postgres from scratch every time an endpoint is called,
the same way keeping a phone line open is faster than redialing for every sentence.

WHERE THE DATABASE PASSWORD COMES FROM
The connection details are NOT written in this code. They're read from backend/.env, a file
on your own computer that .gitignore keeps out of GitHub. That way the code can be public
while the password stays private.

HOW TO INTERPRET PYTHON
- # starts a comment. Text in triple quotes is a docstring (a description).
- `def name(...):` defines a function: a named, reusable block of code. The indented lines
  below it are the function's body.
- `-> None` after a function means it doesn't hand back a result; it just does something.
"""

# IMPORTS: load tools from Python and from installed libraries.
import os  # Reads environment variables (settings stored outside the code).
from collections.abc import Iterator  # Used only in a type hint below.
from pathlib import Path  # Builds file paths that work on any operating system.

from dotenv import load_dotenv  # Reads a .env file and turns its lines into environment variables.
from psycopg import Connection  # psycopg is the library that talks to PostgreSQL.
from psycopg.rows import dict_row  # Makes query results come back as {column: value} dictionaries.
from psycopg_pool import ConnectionPool  # The connection pool described above.

# LOAD backend/.env
# This reads backend/.env and makes each `NAME=value` line available as an environment variable,
# e.g. DATABASE_URL=postgresql://user:password@localhost:5432/museum_of_play
# Path(__file__).resolve().parents[1] is the backend/ folder (one level up from this file),
# so this works no matter which folder the server is started from.
# If the file doesn't exist (e.g. on a server where DATABASE_URL is set another way), nothing breaks.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# THE POOL ITSELF
# `_pool` is a variable that will hold the connection pool once it's opened.
# `: ConnectionPool | None` is a type hint meaning "either a ConnectionPool or None".
# None is Python's word for "nothing" or "empty", like null in JSON.
# It starts empty because the pool is created at startup (see main.py), not when this file loads,
# so simply loading the code never tries to reach the database.
# The leading underscore is a convention meaning "only meant to be used inside this file".
_pool: ConnectionPool | None = None

def open_pool() -> None:
    """Open the connection pool. Called once when the app starts."""
    # `global _pool` lets this function replace the `_pool` variable defined above,
    # instead of creating a separate variable that only exists inside this function.
    global _pool
    # Read DATABASE_URL from the environment (which load_dotenv filled in from backend/.env).
    # If it isn't set, .get returns None.
    database_url = os.environ.get("DATABASE_URL")
    # `if not database_url:` means "if it's missing or empty".
    # `raise` stops the program with an error message; here it stops the server from starting
    # and explains what to fix.
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Add it to backend/.env.")
    # Create the pool (but don't connect yet: open=False).
    # conninfo= is the connection string. kwargs= passes extra settings to every connection:
    # row_factory=dict_row makes each result row a dictionary keyed by column name,
    # e.g. {"artist_id": "ART-JST-0001", "artist_name": "Julia St-Croix", ...},
    # which lines up directly with the models in models.py.
    _pool = ConnectionPool(
        conninfo=database_url,
        kwargs={"row_factory": dict_row},
        open=False,
    )
    
    # Now connect. wait=True means "don't continue until at least one connection works".
    # If the password or database name is wrong, the pool retries for 30 seconds and then
    # stops the server with a PoolTimeout error. The first "error connecting" line printed
    # above that error in the terminal shows the real cause.
    _pool.open(wait=True)

def close_pool() -> None:
    """Close the connection pool. Called once when the app shuts down."""
    global _pool
    # `is not None` checks that the pool was actually opened before trying to close it.
    if _pool is not None:
        _pool.close()
        _pool = None

def get_db() -> Iterator[Connection]:
    """FastAPI dependency that lends a connection to one request.

    Endpoints receive it by declaring a `conn` parameter with `Depends(get_db)`.
    ("Depends" is FastAPI's way of saying "run this function first and give me its result".)
    The transaction commits if the request succeeds and rolls back if it raises,
    so a request that fails halfway never leaves partial changes in the database.
    """
    if _pool is None:
        raise RuntimeError("Connection pool is not open.")
    # `with _pool.connection() as conn:` borrows a connection from the pool and names it `conn`.
    # When the indented block finishes, the connection is automatically returned to the pool,
    # and its changes are saved (committed), or undone (rolled back) if an error occurred.
    with _pool.connection() as conn:
        # `yield` hands the connection to the endpoint and waits until the endpoint is finished.
        # Only then does the `with` block end and the connection go back to the pool.
        yield conn
