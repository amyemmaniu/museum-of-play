"""Entry point for the Museum of Play Collections API.

This file only wires the app together; it contains no endpoint logic. It:
- opens the database connection pool when the server starts and closes it when it stops,
- registers the error handlers that turn every error into application/problem+json,
- includes the routers that define the endpoints, and
- replaces FastAPI's auto-generated spec with the bundled Redocly spec, so /docs shows
  exactly what is written in openapi/.

Run from the repo root with `uv run fastapi dev --port 3000`
(pyproject.toml points FastAPI at `backend.app.main:app`).
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder

# Relative imports (the leading dot) work whether the app is started from the repo root
# (as `backend.app.main`) or from backend/ (as `app.main`).
from .database import close_pool, open_pool
from .errors import register_exception_handlers
from .routers import artists, artworks, exhibitions

logger = logging.getLogger(__name__)

# The bundled Redocly spec. Run `npm run bundle` from the repo root to create or refresh it.
# parents[2] walks up from backend/app/main.py to the repo root.
SPEC_PATH = Path(__file__).resolve().parents[2] / "dist" / "openapi.yaml"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run setup before the server accepts requests, and cleanup after it stops."""
    # Opening the pool at startup means a wrong DATABASE_URL fails immediately,
    # instead of on the first request.
    open_pool()
    yield
    close_pool()

app = FastAPI(title="Museum of Play Collections API", lifespan=lifespan)

register_exception_handlers(app)

# Each router adds the endpoints for one resource (see backend/app/routers/).
app.include_router(artists.router)
app.include_router(artworks.router)
app.include_router(exhibitions.router)

def custom_openapi() -> dict:
    """Serve the Redocly spec at /openapi.json instead of FastAPI's generated one.

    Swagger UI at /docs reads /openapi.json, so this is what makes /docs match openapi/.
    The spec is read once and cached; restart the server after running `npm run bundle`.
    """
    if app.openapi_schema:
        return app.openapi_schema
    if SPEC_PATH.exists():
        with SPEC_PATH.open(encoding="utf-8") as f:
            # jsonable_encoder converts any YAML values JSON can't represent (such as an
            # unquoted date) into strings, so the spec can be sent as JSON.
            app.openapi_schema = jsonable_encoder(yaml.safe_load(f))
    else:
        # Fall back to FastAPI's generated spec so /docs still works without a bundle.
        logger.warning("%s not found; serving FastAPI's generated spec. Run `npm run bundle`.", SPEC_PATH)
        app.openapi_schema = FastAPI.openapi(app)
    return app.openapi_schema

app.openapi = custom_openapi
