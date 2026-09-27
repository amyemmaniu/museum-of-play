"""Endpoints for /artists (public.artists), defined in openapi/paths/artists*.yaml.

Only GET /artists is implemented so far. The other operations in the spec (POST /artists and
GET/PATCH/DELETE /artists/{artist_id}) return 404 until they're added here, following the
same pattern as routers/artworks.py.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from psycopg import Connection

from ..database import get_db
from ..models import Artist, ListResponse
from ..queries import list_page

# prefix: every route below starts with /artists. tags: groups these endpoints under "Artists" in /docs.
router = APIRouter(prefix="/artists", tags=["Artists"])

# TABLE, KEY, and COLUMNS are also used by routers/exhibitions.py for /exhibitions/{id}/artists.
TABLE = "artists"
KEY = "artist_id"
# Columns that `sort` and `filter` accept. Anything else is rejected, so user input never becomes SQL.
COLUMNS = (
    "artist_id",
    "artist_name",
    "birth_year",
    "death_year",
    "gender",
    "nationality",
    "based_in_place",
)
# Text columns that `search` matches against (Search.yaml).
SEARCH_COLUMNS = ("artist_id", "artist_name", "gender", "nationality", "based_in_place")


@router.get("", response_model=ListResponse[Artist])
def list_artists(
    conn: Annotated[Connection, Depends(get_db)],
    after: str | None = None,
    before: str | None = None,
    sort: str | None = None,
    filter: str | None = None,
    search: str | None = None,
    # Query(ge=1, le=100) enforces Limit.yaml's range; anything outside it returns 400.
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    """GET /artists (listArtists): a page of artists, with optional sort, filter, and search."""
    return list_page(
        conn,
        table=TABLE,
        key=KEY,
        columns=COLUMNS,
        search_columns=SEARCH_COLUMNS,
        resource="artists",
        after=after,
        before=before,
        sort=sort,
        filter=filter,
        search=search,
        limit=limit,
    )
