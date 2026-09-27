"""Endpoints for /exhibitions, defined in openapi/paths/exhibitions*.yaml.

This router covers three tables:
- public.exhibitions: list, add, get, update, and delete exhibitions.
- public.exhibitions_artists: list, add, and remove the artists featured in an exhibition.
- public.exhibitions_artworks: list, add, and remove the artworks featured in an exhibition.

The join-table endpoints live here, rather than in artists.py or artworks.py, because their
URLs all start with /exhibitions.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from psycopg import Connection, sql

from ..database import get_db
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
# Reuse the artists and artworks routers' table names and column lists for the join-table lists.
from . import artists, artworks

# prefix: every route below starts with /exhibitions. tags: groups these endpoints under "Exhibitions" in /docs.
router = APIRouter(prefix="/exhibitions", tags=["Exhibitions"])

TABLE = "exhibitions"
KEY = "exhibition_id"
# Columns that `sort` and `filter` accept.
COLUMNS = (
    "exhibition_id",
    "start_date",
    "end_date",
    "exhibition_name",
    "curator",
    "type",
    "location",
)
# Text columns that `search` matches against (Search.yaml).
SEARCH_COLUMNS = ("exhibition_id", "exhibition_name", "curator", "type", "location")

# Reusable parameter types. Each path pattern rejects a malformed ID with 400 before any SQL runs.
ExhibitionId = Annotated[str, Path(pattern=EXHIBITION_ID_PATTERN)]
ArtistId = Annotated[str, Path(pattern=ARTIST_ID_PATTERN)]
AccessionNumber = Annotated[str, Path(pattern=ACCESSION_NUMBER_PATTERN)]
Db = Annotated[Connection, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=100)]


# /exhibitions and /exhibitions/{exhibition_id}

@router.get("", response_model=ListResponse[Exhibition])
def list_exhibitions(
    conn: Db,
    after: str | None = None,
    before: str | None = None,
    sort: str | None = None,
    filter: str | None = None,
    search: str | None = None,
    limit: Limit = 10,
):
    """GET /exhibitions (listExhibitions): a page of exhibitions, with optional sort, filter, and search."""
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


@router.post("", status_code=201, response_model=Exhibition)
def add_exhibition(exhibition: Exhibition, conn: Db):
    """POST /exhibitions (addExhibition): add an exhibition and return it with 201 Created."""
    insert_row(conn, TABLE, exhibition.model_dump())
    # Read the row back so the response shows exactly what was stored.
    return get_row(conn, TABLE, KEY, exhibition.exhibition_id)


@router.get("/{exhibition_id}", response_model=Exhibition)
def get_exhibition(exhibition_id: ExhibitionId, conn: Db):
    """GET /exhibitions/{exhibition_id} (getExhibition): one exhibition, or 404."""
    exhibition = get_row(conn, TABLE, KEY, exhibition_id)
    if exhibition is None:
        raise HTTPException(404, "Exhibition not found.")
    return exhibition


@router.patch("/{exhibition_id}", response_model=Exhibition)
def update_exhibition(exhibition_id: ExhibitionId, changes: ExhibitionUpdate, conn: Db):
    """PATCH /exhibitions/{exhibition_id} (updateExhibition): change some fields, return the result.

    Changing exhibition_id also updates the join tables, because their foreign keys are
    ON UPDATE CASCADE.
    """
    # JSON Merge Patch: only fields present in the body change; an explicit null clears a field.
    data = changes.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "Include at least one field to update.")
    if not update_row(conn, TABLE, KEY, exhibition_id, data):
        raise HTTPException(404, "Exhibition not found.")
    # If the ID itself was changed, look the exhibition up by its new value.
    return get_row(conn, TABLE, KEY, data.get(KEY, exhibition_id))


@router.delete("/{exhibition_id}", status_code=204)
def delete_exhibition(exhibition_id: ExhibitionId, conn: Db):
    """DELETE /exhibitions/{exhibition_id} (deleteExhibition): 204 on success, 404 if not found."""
    # Exhibitions with featured artists or artworks can't be deleted; the foreign key raises a 409.
    if not delete_row(conn, TABLE, KEY, exhibition_id):
        raise HTTPException(404, "Exhibition not found.")
    return Response(status_code=204)


# /exhibitions/{exhibition_id}/artists (public.exhibitions_artists)

@router.get("/{exhibition_id}/artists", response_model=ListResponse[Artist])
def list_exhibition_artists(
    exhibition_id: ExhibitionId,
    conn: Db,
    after: str | None = None,
    before: str | None = None,
    sort: str | None = None,
    limit: Limit = 10,
):
    """GET /exhibitions/{exhibition_id}/artists (listExhibitionArtists): the artists in one exhibition."""
    # Check first, so an unknown exhibition returns 404 rather than an empty list.
    require_row(conn, TABLE, KEY, exhibition_id, "Exhibition")
    # Select from artists, keeping only those with a row in the join table for this exhibition.
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


@router.put("/{exhibition_id}/artists/{artist_id}", status_code=204)
def add_exhibition_artist(exhibition_id: ExhibitionId, artist_id: ArtistId, conn: Db):
    """PUT /exhibitions/{exhibition_id}/artists/{artist_id} (addExhibitionArtist): feature an artist."""
    # Check both records exist so the client gets a 404 that says which one is missing.
    require_row(conn, TABLE, KEY, exhibition_id, "Exhibition")
    require_row(conn, artists.TABLE, artists.KEY, artist_id, "Artist")
    # Idempotent: adding an artist who is already featured does nothing.
    conn.execute(
        "INSERT INTO exhibitions_artists (exhibition_id, artist_id) VALUES (%s, %s) "
        "ON CONFLICT DO NOTHING",
        [exhibition_id, artist_id],
    )
    return Response(status_code=204)


@router.delete("/{exhibition_id}/artists/{artist_id}", status_code=204)
def remove_exhibition_artist(exhibition_id: ExhibitionId, artist_id: ArtistId, conn: Db):
    """DELETE /exhibitions/{exhibition_id}/artists/{artist_id} (removeExhibitionArtist).

    Removes the link only; the artist record itself isn't deleted.
    """
    cursor = conn.execute(
        "DELETE FROM exhibitions_artists WHERE exhibition_id = %s AND artist_id = %s",
        [exhibition_id, artist_id],
    )
    # rowcount is 0 when there was no such link to remove.
    if cursor.rowcount == 0:
        raise HTTPException(404, "Artist is not featured in this exhibition.")
    return Response(status_code=204)


# /exhibitions/{exhibition_id}/artworks (public.exhibitions_artworks)

@router.get("/{exhibition_id}/artworks", response_model=ListResponse[Artwork])
def list_exhibition_artworks(
    exhibition_id: ExhibitionId,
    conn: Db,
    after: str | None = None,
    before: str | None = None,
    sort: str | None = None,
    limit: Limit = 10,
):
    """GET /exhibitions/{exhibition_id}/artworks (listExhibitionArtworks): the artworks in one exhibition."""
    require_row(conn, TABLE, KEY, exhibition_id, "Exhibition")
    # Select from artworks, keeping only those with a row in the join table for this exhibition.
    # artworks.SELECT returns runtime as HH:MM:SS, the same as the /artworks endpoints.
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


@router.put("/{exhibition_id}/artworks/{accession_number}", status_code=204)
def add_exhibition_artwork(
    exhibition_id: ExhibitionId, accession_number: AccessionNumber, conn: Db
):
    """PUT /exhibitions/{exhibition_id}/artworks/{accession_number} (addExhibitionArtwork): feature an artwork."""
    require_row(conn, TABLE, KEY, exhibition_id, "Exhibition")
    require_row(conn, artworks.TABLE, artworks.KEY, accession_number, "Artwork")
    # Idempotent: adding an artwork that is already featured does nothing.
    conn.execute(
        "INSERT INTO exhibitions_artworks (exhibition_id, accession_number) VALUES (%s, %s) "
        "ON CONFLICT DO NOTHING",
        [exhibition_id, accession_number],
    )
    return Response(status_code=204)


@router.delete("/{exhibition_id}/artworks/{accession_number}", status_code=204)
def remove_exhibition_artwork(
    exhibition_id: ExhibitionId, accession_number: AccessionNumber, conn: Db
):
    """DELETE /exhibitions/{exhibition_id}/artworks/{accession_number} (removeExhibitionArtwork).

    Removes the link only; the artwork record itself isn't deleted.
    """
    cursor = conn.execute(
        "DELETE FROM exhibitions_artworks WHERE exhibition_id = %s AND accession_number = %s",
        [exhibition_id, accession_number],
    )
    # rowcount is 0 when there was no such link to remove.
    if cursor.rowcount == 0:
        raise HTTPException(404, "Artwork is not featured in this exhibition.")
    return Response(status_code=204)
