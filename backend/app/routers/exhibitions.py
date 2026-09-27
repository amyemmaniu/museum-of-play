"""Endpoints for /exhibitions, defined in openapi/paths/exhibitions*.yaml.

WHAT THIS FILE DOES
A router is a group of related endpoints. This one handles every URL starting with
/exhibitions, which covers three database tables:
- public.exhibitions: list, add, get one, update, and delete exhibitions.
- public.exhibitions_artists: list, add, and remove the artists featured in an exhibition.
- public.exhibitions_artworks: list, add, and remove the artworks featured in an exhibition.

The last two are "join tables": each row just links one exhibition to one artist or artwork.
Their endpoints live here, rather than in artists.py or artworks.py, because their URLs all
start with /exhibitions.

HOW TO INTERPRET PYTHON
- `@router.get(...)`, `@router.put(...)`, etc. above a function register it as the handler
  for that HTTP method and URL. FastAPI runs the function when a matching request arrives.
- "{exhibition_id}" in a URL is a path parameter: that part of the URL becomes the function
  input with the same name.
- An input whose type is a model (e.g. `exhibition: Exhibition`) is read from the JSON body.
- `raise HTTPException(404, "...")` stops and sends an error response.
- `return` sends a result back as the response.
"""

# IMPORTS
from typing import Annotated  # Lets an input carry extra rules, such as a pattern.

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from psycopg import Connection, sql

# The two dots mean "from the folder one level up" (backend/app/).
from ..database import get_db
# Several names imported at once; the parentheses let the list span multiple lines.
from ..models import (
    ACCESSION_NUMBER_PATTERN,
    ARTIST_ID_PATTERN,
    EXHIBITION_ID_PATTERN,
    Artist,
    Artwork,
    Exhibition,
    ExhibitionUpdate,
    ListResponse,
)
from ..queries import delete_row, get_row, insert_row, list_page, require_row, update_row
# The single dot means "from this same folder" (routers/). This loads the artists and artworks
# routers so their table names and column lists can be reused for the join-table lists below.
from . import artists, artworks

# CREATE THE ROUTER
# prefix="/exhibitions": every URL in this file starts with /exhibitions.
# tags=["Exhibitions"]: groups these endpoints under "Exhibitions" in /docs.
router = APIRouter(prefix="/exhibitions", tags=["Exhibitions"])

# SETTINGS FOR THE EXHIBITIONS TABLE
TABLE = "exhibitions"        # The database table name.
KEY = "exhibition_id"        # The table's primary key (the unique ID column).
# Columns that `sort` and `filter` accept. Anything else is rejected with a 400.
COLUMNS = (
    "exhibition_id",
    "start_date",
    "end_date",
    "exhibition_name",
    "curator",
    "type",
    "location",
)
# Text columns that `search` looks in (see Search.yaml).
SEARCH_COLUMNS = ("exhibition_id", "exhibition_name", "curator", "type", "location")

# REUSABLE INPUT TYPES
# IDs taken from the URL. Each must match its pattern; a malformed ID is rejected with a 400
# before any SQL runs.
ExhibitionId = Annotated[str, Path(pattern=EXHIBITION_ID_PATTERN)]      # e.g. EXH-0001
ArtistId = Annotated[str, Path(pattern=ARTIST_ID_PATTERN)]              # e.g. ART-JST-0001
AccessionNumber = Annotated[str, Path(pattern=ACCESSION_NUMBER_PATTERN)]  # e.g. 2021.0001
# A database connection, supplied by FastAPI through get_db (see database.py).
Db = Annotated[Connection, Depends(get_db)]
# The `limit` query parameter: a whole number from 1 to 100 (Limit.yaml).
Limit = Annotated[int, Query(ge=1, le=100)]

# ---------------------------------------------------------------------------
# /exhibitions and /exhibitions/{exhibition_id}
# ---------------------------------------------------------------------------

# GET /exhibitions: list exhibitions
@router.get("", response_model=ListResponse[Exhibition])
def list_exhibitions(
    conn: Db,
    # The optional query parameters from the spec (e.g. /exhibitions?filter=type:solo).
    after: str | None = None,
    before: str | None = None,
    sort: str | None = None,
    filter: str | None = None,
    search: str | None = None,
    limit: Limit = 10,
):
    """GET /exhibitions (listExhibitions): a page of exhibitions, with optional sort, filter, and search."""
    # Hand everything to the shared list function in queries.py.
    return list_page(
        conn,
        table=TABLE,
        key=KEY,
        columns=COLUMNS,
        search_columns=SEARCH_COLUMNS,
        resource="exhibitions",
        after=after,
        before=before,
        sort=sort,
        filter=filter,
        search=search,
        limit=limit,
    )

# POST /exhibitions: add an exhibition
# status_code=201 means "Created", the status the spec documents for a successful POST.
@router.post("", status_code=201, response_model=Exhibition)
def add_exhibition(exhibition: Exhibition, conn: Db):
    """POST /exhibitions (addExhibition): add an exhibition and return it with 201 Created."""
    # model_dump() turns the model into a dictionary of column names and values to insert.
    insert_row(conn, TABLE, exhibition.model_dump())
    # Read the new row back so the response shows exactly what was stored.
    return get_row(conn, TABLE, KEY, exhibition.exhibition_id)

# GET /exhibitions/{exhibition_id}: get one exhibition
@router.get("/{exhibition_id}", response_model=Exhibition)
def get_exhibition(exhibition_id: ExhibitionId, conn: Db):
    """GET /exhibitions/{exhibition_id} (getExhibition): one exhibition, or 404 if it doesn't exist."""
    exhibition = get_row(conn, TABLE, KEY, exhibition_id)
    # get_row returns None when no row matches.
    if exhibition is None:
        raise HTTPException(404, "Exhibition not found.")
    return exhibition

# PATCH /exhibitions/{exhibition_id}: change some fields of an exhibition
@router.patch("/{exhibition_id}", response_model=Exhibition)
def update_exhibition(exhibition_id: ExhibitionId, changes: ExhibitionUpdate, conn: Db):
    """PATCH /exhibitions/{exhibition_id} (updateExhibition): change some fields, return the result.

    Changing exhibition_id also updates the links in the join tables automatically, because
    their foreign keys are ON UPDATE CASCADE.
    """
    # JSON Merge Patch: only the fields in the request body change, and a field sent as null is
    # cleared. exclude_unset=True keeps only the fields the client actually sent.
    data = changes.model_dump(exclude_unset=True)
    # An empty body would change nothing, so treat it as a mistake.
    if not data:
        raise HTTPException(400, "Include at least one field to update.")
    # update_row returns False if no exhibition had this ID.
    if not update_row(conn, TABLE, KEY, exhibition_id, data):
        raise HTTPException(404, "Exhibition not found.")
    # Return the updated exhibition, looked up by its new ID if the ID itself was changed.
    return get_row(conn, TABLE, KEY, data.get(KEY, exhibition_id))

# DELETE /exhibitions/{exhibition_id}: delete an exhibition
@router.delete("/{exhibition_id}", status_code=204)
def delete_exhibition(exhibition_id: ExhibitionId, conn: Db):
    """DELETE /exhibitions/{exhibition_id} (deleteExhibition): 204 on success, 404 if not found."""
    # Exhibitions that still have featured artists or artworks can't be deleted: the database
    # refuses, and errors.py turns that into a 409 Conflict. Remove the links first.
    if not delete_row(conn, TABLE, KEY, exhibition_id):
        raise HTTPException(404, "Exhibition not found.")
    # 204 No Content: success, with an empty response body.
    return Response(status_code=204)

# ---------------------------------------------------------------------------
# /exhibitions/{exhibition_id}/artists (public.exhibitions_artists join table)
# ---------------------------------------------------------------------------

# GET /exhibitions/{exhibition_id}/artists: list the artists in an exhibition
@router.get("/{exhibition_id}/artists", response_model=ListResponse[Artist])
def list_exhibition_artists(
    exhibition_id: ExhibitionId,
    conn: Db,
    # The spec only offers paging and sorting here (no filter or search).
    after: str | None = None,
    before: str | None = None,
    sort: str | None = None,
    limit: Limit = 10,
):
    """GET /exhibitions/{exhibition_id}/artists (listExhibitionArtists): the artists in one exhibition."""
    # Check the exhibition exists first, so an unknown ID returns 404 instead of an empty list.
    require_row(conn, TABLE, KEY, exhibition_id, "Exhibition")
    # Read from the artists table, keeping only artists that have a row in the join table for
    # this exhibition. In SQL:
    #   FROM artists AS t
    #   JOIN exhibitions_artists AS link ON link.artist_id = t.artist_id
    #   WHERE link.exhibition_id = <exhibition_id>
    return list_page(
        conn,
        table=artists.TABLE,
        key=artists.KEY,
        columns=artists.COLUMNS,
        resource="artists",
        join=sql.SQL("JOIN exhibitions_artists AS link ON link.artist_id = t.artist_id"),
        conditions=[sql.SQL("link.exhibition_id = %s")],
        params=[exhibition_id],
        after=after,
        before=before,
        sort=sort,
        limit=limit,
    )

# PUT /exhibitions/{exhibition_id}/artists/{artist_id}: feature an artist in an exhibition
@router.put("/{exhibition_id}/artists/{artist_id}", status_code=204)
def add_exhibition_artist(exhibition_id: ExhibitionId, artist_id: ArtistId, conn: Db):
    """PUT /exhibitions/{exhibition_id}/artists/{artist_id} (addExhibitionArtist): feature an artist."""
    # Check both records exist, so the 404 message says which one is missing.
    require_row(conn, TABLE, KEY, exhibition_id, "Exhibition")
    require_row(conn, artists.TABLE, artists.KEY, artist_id, "Artist")
    # Add the link. "ON CONFLICT DO NOTHING" means that if the link already exists, nothing
    # happens and no error is raised. This makes the request "idempotent": sending it twice has
    # the same effect as sending it once, as the spec describes.
    conn.execute(
        "INSERT INTO exhibitions_artists (exhibition_id, artist_id) VALUES (%s, %s) "
        "ON CONFLICT DO NOTHING",
        [exhibition_id, artist_id],
    )
    # 204 No Content: success, with an empty response body.
    return Response(status_code=204)

# DELETE /exhibitions/{exhibition_id}/artists/{artist_id}: remove an artist from an exhibition
@router.delete("/{exhibition_id}/artists/{artist_id}", status_code=204)
def remove_exhibition_artist(exhibition_id: ExhibitionId, artist_id: ArtistId, conn: Db):
    """DELETE /exhibitions/{exhibition_id}/artists/{artist_id} (removeExhibitionArtist).

    Removes the link only; the artist record itself isn't deleted.
    """
    # Delete the one join-table row linking this exhibition and artist.
    cursor = conn.execute(
        "DELETE FROM exhibitions_artists WHERE exhibition_id = %s AND artist_id = %s",
        [exhibition_id, artist_id],
    )
    # rowcount is how many rows were deleted; 0 means there was no such link.
    if cursor.rowcount == 0:
        raise HTTPException(404, "Artist is not featured in this exhibition.")
    return Response(status_code=204)

# ---------------------------------------------------------------------------
# /exhibitions/{exhibition_id}/artworks (public.exhibitions_artworks join table)
# ---------------------------------------------------------------------------

# GET /exhibitions/{exhibition_id}/artworks: list the artworks in an exhibition
@router.get("/{exhibition_id}/artworks", response_model=ListResponse[Artwork])
def list_exhibition_artworks(
    exhibition_id: ExhibitionId,
    conn: Db,
    # The spec only offers paging and sorting here (no filter or search).
    after: str | None = None,
    before: str | None = None,
    sort: str | None = None,
    limit: Limit = 10,
):
    """GET /exhibitions/{exhibition_id}/artworks (listExhibitionArtworks): the artworks in one exhibition."""
    # Check the exhibition exists first, so an unknown ID returns 404 instead of an empty list.
    require_row(conn, TABLE, KEY, exhibition_id, "Exhibition")
    # Read from the artworks table, keeping only artworks that have a row in the join table for
    # this exhibition. artworks.SELECT returns runtime as HH:MM:SS, the same as /artworks.
    return list_page(
        conn,
        table=artworks.TABLE,
        key=artworks.KEY,
        columns=artworks.COLUMNS,
        select=artworks.SELECT,
        resource="artworks",
        join=sql.SQL(
            "JOIN exhibitions_artworks AS link ON link.accession_number = t.accession_number"
        ),
        conditions=[sql.SQL("link.exhibition_id = %s")],
        params=[exhibition_id],
        after=after,
        before=before,
        sort=sort,
        limit=limit,
    )

# PUT /exhibitions/{exhibition_id}/artworks/{accession_number}: feature an artwork in an exhibition
@router.put("/{exhibition_id}/artworks/{accession_number}", status_code=204)
def add_exhibition_artwork(
    exhibition_id: ExhibitionId, accession_number: AccessionNumber, conn: Db
):
    """PUT /exhibitions/{exhibition_id}/artworks/{accession_number} (addExhibitionArtwork): feature an artwork."""
    # Check both records exist, so the 404 message says which one is missing.
    require_row(conn, TABLE, KEY, exhibition_id, "Exhibition")
    require_row(conn, artworks.TABLE, artworks.KEY, accession_number, "Artwork")
    # Add the link; if it already exists, do nothing (idempotent, as described above).
    conn.execute(
        "INSERT INTO exhibitions_artworks (exhibition_id, accession_number) VALUES (%s, %s) "
        "ON CONFLICT DO NOTHING",
        [exhibition_id, accession_number],
    )
    return Response(status_code=204)

# DELETE /exhibitions/{exhibition_id}/artworks/{accession_number}: remove an artwork from an exhibition
@router.delete("/{exhibition_id}/artworks/{accession_number}", status_code=204)
def remove_exhibition_artwork(
    exhibition_id: ExhibitionId, accession_number: AccessionNumber, conn: Db
):
    """DELETE /exhibitions/{exhibition_id}/artworks/{accession_number} (removeExhibitionArtwork).

    Removes the link only; the artwork record itself isn't deleted.
    """
    # Delete the one join-table row linking this exhibition and artwork.
    cursor = conn.execute(
        "DELETE FROM exhibitions_artworks WHERE exhibition_id = %s AND accession_number = %s",
        [exhibition_id, accession_number],
    )
    # rowcount is how many rows were deleted; 0 means there was no such link.
    if cursor.rowcount == 0:
        raise HTTPException(404, "Artwork is not featured in this exhibition.")
    return Response(status_code=204)
