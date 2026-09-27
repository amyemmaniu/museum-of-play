"""Endpoints for /artists (public.artists table), defined in openapi/paths/artists*.yaml.

WHAT THIS FILE DOES
A "router" is a group of related endpoints. This one handles URLs starting with /artists.

Only GET /artists is built so far. The other operations in the spec (POST /artists and
GET/PATCH/DELETE /artists/{artist_id}) return 404 until they're added here, following the
same pattern as routers/artworks.py.

HOW TO INTERPRET PYTHON
- `@router.get("")` above a function is a "decorator": it registers the function as the
  handler for GET requests to this router's URL. When someone calls GET /artists,
  FastAPI runs the function below it and sends back whatever it returns.
- A function's inputs become the request's parameters. For example, `sort: str | None = None`
  means the URL can include ?sort=... (optional text, empty if left out).
- `Annotated[type, extra]` attaches extra rules to an input, such as a number range.
"""

# IMPORTS
from typing import Annotated  # Lets an input carry extra rules (see the guide above).

from fastapi import APIRouter, Depends, Query
from psycopg import Connection

# The two dots mean "from the folder one level up" (backend/app/).
from ..database import get_db  # Lends each request a database connection.
from ..models import Artist, ListResponse  # The response shape (models.py).
from ..queries import list_page  # The shared list/sort/filter/search/pagination logic.

# CREATE THE ROUTER
# prefix="/artists": every URL in this file starts with /artists.
# tags=["Artists"]: groups these endpoints under "Artists" in /docs.
router = APIRouter(prefix="/artists", tags=["Artists"])

# SETTINGS FOR THIS TABLE
# These are also used by routers/exhibitions.py for /exhibitions/{id}/artists.
TABLE = "artists"        # The database table name.
KEY = "artist_id"        # The table's primary key (the unique ID column).
# Columns that `sort` and `filter` accept. Anything else is rejected, so text from a request
# can never be used as a column name in SQL.
# Values in parentheses separated by commas form a "tuple": a fixed list that can't be changed.
COLUMNS = (
    "artist_id",
    "artist_name",
    "birth_year",
    "death_year",
    "gender",
    "nationality",
    "based_in_place",
)
# Text columns that `search` looks in (see Search.yaml).
SEARCH_COLUMNS = ("artist_id", "artist_name", "gender", "nationality", "based_in_place")


# GET /artists
# response_model=ListResponse[Artist]: the response must have the ArtistList shape.
@router.get("", response_model=ListResponse[Artist])
def list_artists(
    # Not a URL parameter: Depends(get_db) makes FastAPI supply a database connection here.
    conn: Annotated[Connection, Depends(get_db)],
    # The optional query parameters from the spec (e.g. /artists?sort=-birth_year&limit=5).
    after: str | None = None,
    before: str | None = None,
    sort: str | None = None,
    filter: str | None = None,
    search: str | None = None,
    # A whole number from 1 to 100 (ge = at least, le = at most), 10 if not given (Limit.yaml).
    # Anything outside that range returns 400.
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    """GET /artists (listArtists): a page of artists, with optional sort, filter, and search."""
    # Hand everything to the shared list function in queries.py, telling it which table and
    # columns to use. Its result is sent back as the response.
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
