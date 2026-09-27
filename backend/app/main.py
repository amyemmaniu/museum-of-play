"""Entry point for the Museum of Play Collections API.

WHAT THIS FILE DOES
This is the first file that runs when the server starts. It doesn't define any endpoints
itself; it connects the other files together. It:
- opens the database connection pool when the server starts and closes it when it stops,
- registers the error handlers that turn every error into application/problem+json,
- includes the routers that define the endpoints, and
- replaces FastAPI's auto-generated spec with the bundled Redocly spec, so /docs shows
  exactly what is written in openapi/.

HOW TO INTERPRET PYTHON
- Lines starting with # are comments; Python ignores them.
- Text between triple quotes, like this block, is a "docstring": a comment that describes
  the file or function it sits at the top of.
- Python uses indentation (spaces at the start of a line) instead of curly braces to show
  which lines belong together, e.g. which lines are inside a function or an `if`.
"""

# IMPORTS
# `import x` and `from x import y` load code from another file or library so this file can use it.
# The first group comes from Python itself or from installed libraries.
import logging  # Python's built-in tool for printing warnings and errors to the terminal.
from contextlib import asynccontextmanager  # Helper for "run this at startup and this at shutdown".
from pathlib import Path  # Builds file paths that work on Windows, macOS, and Linux.

import yaml  # Reads YAML files for the OpenAPI spec.
from fastapi import FastAPI  # The web framework that turns Python functions into API endpoints.
from fastapi.encoders import jsonable_encoder  # Converts data into a form that can be sent as JSON.

# The second group comes from this project's own files.
# The leading dot means "from the same folder as this file", so `.database` is database.py.
# This style works whether the app is started from the repo root or from backend/.
from .database import close_pool, open_pool
from .errors import register_exception_handlers
from .routers import artists, artworks, exhibitions

# A "logger" prints messages to the terminal where the server is running.
# __name__ is filled in by Python with this file's module name, so messages show where they came from.
logger = logging.getLogger(__name__)

# WHERE THE SPEC LIVES
# The bundled Redocly spec. Run `npm run bundle` from the repo root to create or refresh it.
# Path(__file__) is this file's own location. .resolve() makes it a full path, and
# .parents[2] walks up two folders (backend/app/main.py -> backend/app -> backend -> repo root).
# The `/` operator then joins folder and file names: <repo root>/dist/openapi.yaml.
# Names written in ALL_CAPS are constants: values set once and never changed.
SPEC_PATH = Path(__file__).resolve().parents[2] / "dist" / "openapi.yaml"

# STARTUP AND SHUTDOWN
# `@asynccontextmanager` is a "decorator": a label placed above a function that changes how it
# behaves. It turns the function into a startup/shutdown routine.
# `async def` defines a function that FastAPI runs in the background.
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run setup before the server accepts requests, and cleanup after it stops."""
    # Everything before `yield` runs once, when the server starts.
    # Opening the pool at startup means a wrong DATABASE_URL fails immediately,
    # instead of on the first request.
    open_pool()
    # `yield` pauses here while the server runs and handles requests.
    yield
    # Everything after `yield` runs once, when the server shuts down (e.g. after pressing Ctrl+C).
    close_pool()

# CREATING THE APP
# This creates the application object. `app = ...` stores it in a variable named `app`,
# which is the name pyproject.toml tells FastAPI to look for.
# title= sets the name shown in /docs; `lifespan=` hooks up the startup/shutdown routine above.
app = FastAPI(title="Museum of Play Collections API", lifespan=lifespan)

# Attach the error handlers defined in errors.py.
register_exception_handlers(app)

# CONNECTING THE ENDPOINTS
# Each router is a group of endpoints defined in its own file (see backend/app/routers/).
# include_router adds that group's endpoints to the app.
app.include_router(artists.router)
app.include_router(artworks.router)
app.include_router(exhibitions.router)

# SERVING THE REDOCLY SPEC
# `def` defines a regular function. `-> dict` notes that it returns a dictionary
# (a set of key/value pairs, like a JSON object). These notes after names and arrows are
# "type hints": they document what kind of value is expected but don't change how the code runs.
def custom_openapi() -> dict:
    """Serve the Redocly spec at /openapi.json instead of FastAPI's generated one.

    Swagger UI at /docs reads /openapi.json, so this is what makes /docs match openapi/.
    The spec is read once and cached; restart the server after running `npm run bundle`.
    """
    # If the spec was already loaded earlier, return the saved copy instead of re-reading the file.
    if app.openapi_schema:
        return app.openapi_schema
    # Otherwise, if the bundled file exists, read it.
    if SPEC_PATH.exists():
        # `with ... as f:` opens the file, runs the indented lines, and then closes the file
        # automatically, even if something goes wrong.
        with SPEC_PATH.open(encoding="utf-8") as f:
            # yaml.safe_load turns the YAML text into Python data. jsonable_encoder then converts
            # any values JSON can't represent (such as an unquoted date) into strings.
            app.openapi_schema = jsonable_encoder(yaml.safe_load(f))
    # `else:` runs when the `if` above was false, i.e. the bundle doesn't exist.
    else:
        # Fall back to FastAPI's generated spec so /docs still works without a bundle,
        # and print a warning in the terminal explaining how to fix it.
        logger.warning("%s not found; serving FastAPI's generated spec. Run `npm run bundle`.", SPEC_PATH)
        app.openapi_schema = FastAPI.openapi(app)
    # `return` sends the result back to whoever called this function.
    return app.openapi_schema

# Tell FastAPI to use the function above whenever it needs the spec (for /openapi.json and /docs).
app.openapi = custom_openapi
