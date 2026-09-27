"""Endpoints for /artworks (public.artworks table), defined in openapi/paths/artworks*.yaml.

WHAT THIS FILE DOES
A router is a group of related endpoints. This one handles URLs starting with /artworks:
list, add, get one, update, and delete artworks.

Each endpoint is a thin layer over the shared helpers in queries.py:
1. FastAPI checks the input first (using the models and ID patterns), returning 400 if it's wrong.
2. The endpoint runs the query.
3. It returns 404 if the artwork doesn't exist.
Database rule errors (a duplicate ID, an artwork that's still in an exhibition) are turned into
400 or 409 responses by errors.py, so they don't need handling here.

HOW TO INTERPRET PYTHON
- `@router.get(...)`, `@router.post(...)`, etc. above a function register it as the handler
  for that HTTP method and URL. FastAPI runs the function when a matching request arrives.
- "/{accession_number}" in a URL is a path parameter: the part of the URL in that position
  becomes the function input with the same name.
- An input whose type is a model (e.g. `artwork: Artwork`) is read from the JSON request body.
- `raise HTTPException(404, "...")` stops and sends an error response.
- `return` sends a result back as the response.
"""

# IMPORTS
from typing import Annotated  # Lets an input carry extra rules, such as a pattern.

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from psycopg import Connection, sql

# The two dots mean "from the folder one level up" (backend/app/).
from ..database import get_db
from ..models import ACCESSION_NUMBER_PATTERN, Artwork, ArtworkUpdate, ListResponse
from ..queries import delete_row, get_row, insert_row, list_page, update_row

# CREATE THE ROUTER
# prefix="/artworks": every URL in this file starts with /artworks.
# tags=["Artworks"]: groups these endpoints under "Artworks" in /docs.
router = APIRouter(prefix="/artworks", tags=["Artworks"])

# SETTINGS FOR THIS TABLE
# TABLE, KEY, COLUMNS, and SELECT are also used by routers/exhibitions.py for
# /exhibitions/{id}/artworks.
TABLE = "artworks"             # The database table name.
KEY = "accession_number"       # The table's primary key (the unique ID column).
# Columns that `sort` and `filter` accept. Anything else is rejected with a 400.
COLUMNS = (
    "accession_number",
    "title",
    "artist_id",
    "medium",
    "dimensions",
    "creation_year",
    "runtime",
)
# Text columns that `search` looks in (see Search.yaml).
SEARCH_COLUMNS = ("accession_number", "medium", "title", "artist_id", "dimensions")
# Which columns to return, written out so runtime can be converted.
# runtime is stored as an interval (a length of time). "runtime::text" converts it to text, so
# it comes back as HH:MM:SS (e.g. "01:30:00") instead of a Python time value.
# Sorting still uses the real interval, so sort=-runtime orders by length, not alphabetically.
# (Two pieces of text in quotes next to each other are joined into one.)
SELECT = sql.SQL(
    "t.accession_number, t.title, t.artist_id, t.medium, t.dimensions, t.creation_year, "
    "t.runtime::text AS runtime"
)

# REUSABLE INPUT TYPES
# An accession number taken from the URL, which must match the pattern (e.g. 2021.0001).
# A malformed one is rejected with a 400 before any SQL runs.
AccessionNumber = Annotated[str, Path(pattern=ACCESSION_NUMBER_PATTERN)]
# A database connection, supplied by FastAPI through get_db (see database.py).
Db = Annotated[Connection, Depends(get_db)]

# GET /artworks: list artworks
@router.get("", response_model=ListResponse[Artwork])
def list_artworks(
    conn: Db,
    # The optional query parameters from the spec (e.g. /artworks?search=blue&limit=5).
    after: str | None = None,
    before: str | None = None,
    sort: str | None = None,
    filter: str | None = None,
    search: str | None = None,
    # A whole number from 1 to 100, 10 if not given (Limit.yaml).
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    """GET /artworks (listArtworks): a page of artworks, with optional sort, filter, and search."""
    # Hand everything to the shared list function in queries.py.
    return list_page(
        conn,
        table=TABLE,
        key=KEY,
        columns=COLUMNS,
        search_columns=SEARCH_COLUMNS,
        select=SELECT,
        resource="artworks",
        after=after,
        before=before,
        sort=sort,
        filter=filter,
        search=search,
        limit=limit,
    )

# POST /artworks: add an artwork
# status_code=201 means "Created", the status the spec documents for a successful POST.
@router.post("", status_code=201, response_model=Artwork)
def add_artwork(artwork: Artwork, conn: Db):
    """POST /artworks (addArtwork): add an artwork and return it with 201 Created.

    The JSON body is checked against the Artwork model first.
    A duplicate accession number returns 409; an artist_id that doesn't exist returns 400.
    """
    # model_dump() turns the model into a dictionary of column names and values to insert.
    insert_row(conn, TABLE, artwork.model_dump())
    # Read the new row back so the response shows exactly what was stored.
    return get_row(conn, TABLE, KEY, artwork.accession_number, SELECT)

# GET /artworks/{accession_number}: get one artwork
@router.get("/{accession_number}", response_model=Artwork)
def get_artwork(accession_number: AccessionNumber, conn: Db):
    """GET /artworks/{accession_number} (getArtwork): one artwork, or 404 if it doesn't exist."""
    artwork = get_row(conn, TABLE, KEY, accession_number, SELECT)
    # get_row returns None when no row matches.
    if artwork is None:
        raise HTTPException(404, "Artwork not found.")
    return artwork

# PATCH /artworks/{accession_number}: change some fields of an artwork
@router.patch("/{accession_number}", response_model=Artwork)
def update_artwork(accession_number: AccessionNumber, changes: ArtworkUpdate, conn: Db):
    """PATCH /artworks/{accession_number} (updateArtwork): change some fields, return the result."""
    # JSON Merge Patch: only the fields in the request body change, and a field sent as null
    # is cleared. exclude_unset=True keeps only the fields the client actually sent, so fields
    # left out of the body aren't touched.
    data = changes.model_dump(exclude_unset=True)
    # An empty body would change nothing, so treat it as a mistake.
    if not data:
        raise HTTPException(400, "Include at least one field to update.")
    # update_row returns False if no artwork had this accession number.
    if not update_row(conn, TABLE, KEY, accession_number, data):
        raise HTTPException(404, "Artwork not found.")
    # Return the updated artwork. If the accession number itself was changed, look it up by the
    # new value: data.get(KEY, accession_number) means "the new accession number if one was
    # sent, otherwise the original".
    return get_row(conn, TABLE, KEY, data.get(KEY, accession_number), SELECT)

# DELETE /artworks/{accession_number}: delete an artwork
@router.delete("/{accession_number}", status_code=204)
def delete_artwork(accession_number: AccessionNumber, conn: Db):
    """DELETE /artworks/{accession_number} (deleteArtwork): 204 on success, 404 if not found."""
    # Artworks featured in an exhibition can't be deleted: the database refuses, and errors.py
    # turns that into a 409 Conflict.
    if not delete_row(conn, TABLE, KEY, accession_number):
        raise HTTPException(404, "Artwork not found.")
    # 204 No Content: success, with an empty response body, as the spec documents.
    return Response(status_code=204)
