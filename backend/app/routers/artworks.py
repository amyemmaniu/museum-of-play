"""Endpoints for /artworks (public.artworks), defined in openapi/paths/artworks*.yaml.

Each endpoint is a thin layer over the helpers in queries.py: validate the input (done by
FastAPI using the models and path patterns), run the query, and return 404 if the row doesn't
exist. Database constraint errors (duplicates, linked records) are handled in errors.py.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from psycopg import Connection, sql

from ..database import get_db
from ..models import ACCESSION_NUMBER_PATTERN, Artwork, ArtworkUpdate, ListResponse
from ..queries import delete_row, get_row, insert_row, list_page, update_row

# prefix: every route below starts with /artworks. tags: groups these endpoints under "Artworks" in /docs.
router = APIRouter(prefix="/artworks", tags=["Artworks"])

# TABLE, KEY, COLUMNS, and SELECT are also used by routers/exhibitions.py for
# /exhibitions/{id}/artworks.
TABLE = "artworks"
KEY = "accession_number"
# Columns that `sort` and `filter` accept.
COLUMNS = (
    "accession_number",
    "title",
    "artist_id",
    "medium",
    "dimensions",
    "creation_year",
    "runtime",
)
# Text columns that `search` matches against (Search.yaml).
SEARCH_COLUMNS = ("accession_number", "medium", "title", "artist_id", "dimensions")
# runtime is an interval; casting to text returns HH:MM:SS instead of a Python timedelta.
# (Sorting still uses the real interval column, so -runtime orders by length, not alphabetically.)
SELECT = sql.SQL(
    "t.accession_number, t.title, t.artist_id, t.medium, t.dimensions, t.creation_year, "
    "t.runtime::text AS runtime"
)

# Reusable parameter types. Path(pattern=...) rejects a malformed accession number with 400
# before any SQL runs. Depends(get_db) gives the endpoint a database connection.
AccessionNumber = Annotated[str, Path(pattern=ACCESSION_NUMBER_PATTERN)]
Db = Annotated[Connection, Depends(get_db)]


@router.get("", response_model=ListResponse[Artwork])
def list_artworks(
    conn: Db,
    after: str | None = None,
    before: str | None = None,
    sort: str | None = None,
    filter: str | None = None,
    search: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    """GET /artworks (listArtworks): a page of artworks, with optional sort, filter, and search."""
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


@router.post("", status_code=201, response_model=Artwork)
def add_artwork(artwork: Artwork, conn: Db):
    """POST /artworks (addArtwork): add an artwork and return it with 201 Created.

    A duplicate accession number returns 409; an artist_id that doesn't exist returns 400.
    """
    insert_row(conn, TABLE, artwork.model_dump())
    # Read the row back so the response shows exactly what was stored.
    return get_row(conn, TABLE, KEY, artwork.accession_number, SELECT)


@router.get("/{accession_number}", response_model=Artwork)
def get_artwork(accession_number: AccessionNumber, conn: Db):
    """GET /artworks/{accession_number} (getArtwork): one artwork, or 404."""
    artwork = get_row(conn, TABLE, KEY, accession_number, SELECT)
    if artwork is None:
        raise HTTPException(404, "Artwork not found.")
    return artwork


@router.patch("/{accession_number}", response_model=Artwork)
def update_artwork(accession_number: AccessionNumber, changes: ArtworkUpdate, conn: Db):
    """PATCH /artworks/{accession_number} (updateArtwork): change some fields, return the result."""
    # JSON Merge Patch: only fields present in the body change; an explicit null clears a field.
    # exclude_unset=True keeps only the fields the client actually sent.
    data = changes.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "Include at least one field to update.")
    if not update_row(conn, TABLE, KEY, accession_number, data):
        raise HTTPException(404, "Artwork not found.")
    # If the accession number itself was changed, look the artwork up by its new value.
    return get_row(conn, TABLE, KEY, data.get(KEY, accession_number), SELECT)


@router.delete("/{accession_number}", status_code=204)
def delete_artwork(accession_number: AccessionNumber, conn: Db):
    """DELETE /artworks/{accession_number} (deleteArtwork): 204 on success, 404 if not found."""
    # Artworks featured in an exhibition can't be deleted; the foreign key raises a 409.
    if not delete_row(conn, TABLE, KEY, accession_number):
        raise HTTPException(404, "Artwork not found.")
    # 204 No Content: success with an empty body, as the spec documents.
    return Response(status_code=204)
