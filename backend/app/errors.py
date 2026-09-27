"""Exception handlers that return errors as application/problem+json, per Error.yaml.

WHAT THIS FILE DOES
When something goes wrong while handling a request, Python raises an exception: it stops
what it was doing and passes an error object upward. An "exception handler" catches one kind
of error and decides what response to send back instead.

Without these handlers, FastAPI would send errors in its own format ({"detail": ...}) with its
own status codes, which wouldn't match the spec. Each handler below catches one kind of error,
picks the status code the spec documents for it, and sends a response shaped like Error.yaml.

This also means endpoints don't need to catch database errors themselves: if a query breaks a
database rule (a duplicate ID, a record that's still linked), the error travels up to here
and is turned into a 400 or 409 response automatically.

HOW TO INTERPRET PYTHON
- `def name(inputs) -> OutputType:` defines a function. The names in parentheses are the
  inputs it receives; `-> JSONResponse` notes what kind of value it returns.
- `async def` is a function FastAPI can run without blocking other requests.
- `request: Request` means "an input named request, which is a Request object".
- `return` sends a result back from the function.
- f"...{x}..." is an "f-string": text with the value of x inserted where {x} appears.
"""

# IMPORTS
import logging  # Prints messages to the terminal where the server is running.
from http import HTTPStatus  # A built-in list of HTTP status codes and their names.
from typing import Any  # Used in type hints to mean "any kind of value".

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder  # Converts data into a form that can be sent as JSON.
from fastapi.exceptions import RequestValidationError  # Raised when request data fails a model's rules.
from fastapi.responses import JSONResponse  # A response whose body is JSON.
# psycopg's error types, one per kind of database problem. Renamed to pg_errors for readability.
from psycopg import errors as pg_errors
# The error type raised by `raise HTTPException(...)` in the routers, and by FastAPI for unknown URLs.
from starlette.exceptions import HTTPException as StarletteHTTPException

# The Problem model (the shape of Error.yaml) from models.py in this same folder.
from .models import Problem

logger = logging.getLogger(__name__)

# SHARED RESPONSE BUILDER

def problem_response(
    request: Request, status: int, details: dict[str, Any] | None = None
) -> JSONResponse:
    """Build an application/problem+json response, the one error shape used by every handler.

    Inputs: the request that failed, the HTTP status code to send, and optional extra details.
    `details: ... = None` means details is optional; it's empty unless a value is passed in.
    """
    # Fill in a Problem model (defined in models.py) with the error's information.
    problem = Problem(
        # The standard phrase for the status code, such as "Not Found" for 404.
        title=HTTPStatus(status).phrase,
        status=status,
        # The path that failed, such as /artworks/2021.0001.
        instance=request.url.path,
        details=details,
    )
    # Send it as the response.
    return JSONResponse(
        status_code=status,
        # exclude_none=True leaves out empty fields instead of sending "details": null.
        content=jsonable_encoder(problem, exclude_none=True),
        # Tells the client this body is a problem-details error, as Error.yaml's responses specify.
        media_type="application/problem+json",
    )

# HANDLERS
# Each function below handles one kind of error. The `exc` input is the error that was raised.

async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Errors raised on purpose in the routers, plus FastAPI's own 404 for unknown URLs.

    Example: `raise HTTPException(404, "Artist not found.")` in a router ends up here.
    """
    # The router's message (e.g. "Artist not found.") goes into details.message.
    details = None
    # Only include a message if it adds something beyond the standard phrase (e.g. "Not Found").
    # `and` means both conditions must be true; `!=` means "is not equal to".
    if exc.detail and exc.detail != HTTPStatus(exc.status_code).phrase:
        details = {"message": exc.detail}
    return problem_response(request, exc.status_code, details)

async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Request data that doesn't match the models or parameter rules.

    Examples: a malformed ID in the URL, a year sent as text, or `limit=500`.
    """
    # FastAPI's default status for this is 422, but the spec documents invalid input as
    # 400 Bad Request, so this changes it to 400.
    # exc.errors() lists each invalid field and why, which helps clients fix the request.
    return problem_response(request, 400, {"errors": exc.errors()})

async def unique_violation_handler(request: Request, exc: pg_errors.UniqueViolation) -> JSONResponse:
    """The database rejected a duplicate ID (the primary key must be unique)."""
    # For example, creating an artist whose artist_id already exists.
    # 409 Conflict: the request is valid, but conflicts with data that already exists.
    return problem_response(
        request, 409, {"message": "A record with this identifier already exists."}
    )

async def foreign_key_violation_handler(
    request: Request, exc: pg_errors.ForeignKeyViolation | pg_errors.RestrictViolation
) -> JSONResponse:
    """A link between tables (a foreign key) was broken. The status depends on which side broke it."""
    # Postgres's error message starts differently depending on what happened, so check it.
    # exc.diag.message_primary is the message; `or ""` uses empty text if there isn't one.
    # .startswith(...) checks whether the text begins with the given words.
    if (exc.diag.message_primary or "").startswith("insert or update on table"):
        # Adding or changing a row to point at something that doesn't exist,
        # e.g. adding an artwork whose artist_id doesn't exist.
        # This is a mistake in the request, so 400 Bad Request.
        return problem_response(
            request, 400, {"message": "A referenced record does not exist."}
        )
    # Otherwise, deleting a row that other rows still point to,
    # e.g. deleting an artist who is still credited on an artwork (ON DELETE RESTRICT).
    # The request is valid but conflicts with existing data, so 409 Conflict.
    return problem_response(
        request, 409, {"message": "This record is linked to other records."}
    )

async def not_null_violation_handler(
    request: Request, exc: pg_errors.NotNullViolation
) -> JSONResponse:
    """A required database column (NOT NULL) was set to empty."""
    # For example, a PATCH that sets an ID to null.
    # exc.diag.column_name is the name of the column that can't be empty.
    return problem_response(
        request, 400, {"message": f"'{exc.diag.column_name}' cannot be null."}
    )

async def data_error_handler(request: Request, exc: pg_errors.DataError) -> JSONResponse:
    """A value the database column can't hold."""
    # For example, a year too large for an int4 column. Postgres's own message explains which.
    return problem_response(request, 400, {"message": exc.diag.message_primary})

async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Anything not caught above. This usually means a bug in the code."""
    # Print the full error in the terminal so it can be debugged...
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    # ...but only send clients a generic 500, so internal details aren't exposed publicly.
    return problem_response(request, 500)

# REGISTERING THE HANDLERS

def register_exception_handlers(app: FastAPI) -> None:
    """Attach every handler to the app. Called once from main.py.

    Each line pairs a kind of error with the function that handles it.
    """
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(pg_errors.UniqueViolation, unique_violation_handler)
    app.add_exception_handler(pg_errors.ForeignKeyViolation, foreign_key_violation_handler)
    # Your foreign keys use ON DELETE RESTRICT, which raises RestrictViolation rather than
    # ForeignKeyViolation, so the same handler is registered for both.
    app.add_exception_handler(pg_errors.RestrictViolation, foreign_key_violation_handler)
    app.add_exception_handler(pg_errors.NotNullViolation, not_null_violation_handler)
    app.add_exception_handler(pg_errors.DataError, data_error_handler)
    # `Exception` matches every error. FastAPI always uses the most specific handler that
    # matches, so this one only catches errors that none of the handlers above cover.
    app.add_exception_handler(Exception, unhandled_exception_handler)
