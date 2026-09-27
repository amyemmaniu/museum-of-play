"""Exception handlers that return errors as application/problem+json, per Error.yaml.

Without these, FastAPI would return errors in its own format ({"detail": ...}) with its own
status codes, which wouldn't match the spec. Each handler catches one kind of error, picks the
status code the spec documents for it, and builds a Problem response.

Endpoints don't need to catch database errors themselves: if a query breaks a constraint,
the psycopg exception bubbles up and the matching handler here turns it into a 400 or 409.
"""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg import errors as pg_errors
from starlette.exceptions import HTTPException as StarletteHTTPException

from .models import Problem

logger = logging.getLogger(__name__)

def problem_response(
    request: Request, status: int, details: dict[str, Any] | None = None
) -> JSONResponse:
    """Build an application/problem+json response, the one error shape used by every handler."""
    problem = Problem(
        # The standard phrase for the status code, such as "Not Found" for 404.
        title=HTTPStatus(status).phrase,
        status=status,
        # The path that failed, such as /artworks/2021.0001.
        instance=request.url.path,
        details=details,
    )
    return JSONResponse(
        status_code=status,
        # exclude_none leaves out empty optional fields instead of sending "details": null.
        content=jsonable_encoder(problem, exclude_none=True),
        media_type="application/problem+json",
    )

async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Errors raised on purpose in the routers, plus FastAPI's own 404 for unknown URLs."""
    # Raise HTTPException(404, "Artist not found.") and the message lands in details.message.
    details = None
    if exc.detail and exc.detail != HTTPStatus(exc.status_code).phrase:
        details = {"message": exc.detail}
    return problem_response(request, exc.status_code, details)

async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Request data that doesn't match the models or parameter rules, such as a bad ID format."""
    # FastAPI defaults to 422, but the spec documents invalid input as 400 Bad Request.
    # exc.errors() lists each invalid field and why, which helps clients fix the request.
    return problem_response(request, 400, {"errors": exc.errors()})

async def unique_violation_handler(request: Request, exc: pg_errors.UniqueViolation) -> JSONResponse:
    """A primary key that already exists."""
    # For example, creating an artist whose artist_id already exists.
    return problem_response(
        request, 409, {"message": "A record with this identifier already exists."}
    )

async def foreign_key_violation_handler(
    request: Request, exc: pg_errors.ForeignKeyViolation | pg_errors.RestrictViolation
) -> JSONResponse:
    """A foreign key was broken. Which status to return depends on which side broke it."""
    # Postgres reports which side of the relationship failed in the message.
    if (exc.diag.message_primary or "").startswith("insert or update on table"):
        # For example, adding an artwork whose artist_id doesn't exist.
        # This is a problem with the request, so 400.
        return problem_response(
            request, 400, {"message": "A referenced record does not exist."}
        )
    # For example, deleting an artist who is still credited on an artwork (ON DELETE RESTRICT).
    # The request is valid but conflicts with existing data, so 409.
    return problem_response(
        request, 409, {"message": "This record is linked to other records."}
    )

async def not_null_violation_handler(
    request: Request, exc: pg_errors.NotNullViolation
) -> JSONResponse:
    """A NOT NULL column was set to null."""
    # For example, a PATCH that sets an ID to null.
    return problem_response(
        request, 400, {"message": f"'{exc.diag.column_name}' cannot be null."}
    )

async def data_error_handler(request: Request, exc: pg_errors.DataError) -> JSONResponse:
    """A value the column type can't hold."""
    # Values Postgres can't store, such as a year outside the int4 range.
    return problem_response(request, 400, {"message": exc.diag.message_primary})

async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Anything else is a bug: log the full error for debugging, but don't expose it to clients."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return problem_response(request, 500)

def register_exception_handlers(app: FastAPI) -> None:
    """Attach every handler to the app. Called once from main.py."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(pg_errors.UniqueViolation, unique_violation_handler)
    app.add_exception_handler(pg_errors.ForeignKeyViolation, foreign_key_violation_handler)
    # ON DELETE RESTRICT foreign keys raise RestrictViolation instead of ForeignKeyViolation.
    app.add_exception_handler(pg_errors.RestrictViolation, foreign_key_violation_handler)
    app.add_exception_handler(pg_errors.NotNullViolation, not_null_violation_handler)
    app.add_exception_handler(pg_errors.DataError, data_error_handler)
    # FastAPI uses the most specific handler that matches, so this only catches what's left.
    app.add_exception_handler(Exception, unhandled_exception_handler)
