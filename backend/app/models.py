"""Pydantic models mirroring the schemas in openapi/components/schemas.

FastAPI uses these models in two directions:
- Request bodies (POST and PATCH) are validated against them before any SQL runs, so a bad
  ID format or a non-integer year returns 400 instead of reaching the database.
- Responses are passed through them (`response_model=`), which guarantees every response has
  exactly the fields and types the spec promises.

Every non-ID column is optional because the matching database column allows NULL.
Field names match the database column names exactly, so rows map onto models with no renaming.
"""

from datetime import date
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

# The same patterns as the ID parameters and schemas in openapi/components.
ARTIST_ID_PATTERN = r"^ART-[A-Z]{3}-[0-9]{4}$"
ACCESSION_NUMBER_PATTERN = r"^[0-9]{4}\.[0-9]{4}$"
EXHIBITION_ID_PATTERN = r"^EXH-[0-9]{4}$"
# HH:MM:SS, up to 23:59:59.
RUNTIME_PATTERN = r"^([0-1][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9])$"

# Artists (public.artists, Artist.yaml)

class Artist(BaseModel):
    """An artist. Used for POST request bodies and for every artist response."""

    artist_id: str = Field(pattern=ARTIST_ID_PATTERN)
    artist_name: str | None = None
    birth_year: int | None = None
    death_year: int | None = None
    gender: str | None = None
    nationality: str | None = None
    based_in_place: str | None = None

class ArtistUpdate(BaseModel):
    """PATCH body: only the fields being changed.

    Every field is optional so a client can send just the fields it wants to change.
    """

    artist_id: str | None = Field(default=None, pattern=ARTIST_ID_PATTERN)
    artist_name: str | None = None
    birth_year: int | None = None
    death_year: int | None = None
    gender: str | None = None
    nationality: str | None = None
    based_in_place: str | None = None

# Artworks (public.artworks, Artwork.yaml)

class Artwork(BaseModel):
    """An artwork. Used for POST request bodies and for every artwork response."""

    accession_number: str = Field(pattern=ACCESSION_NUMBER_PATTERN)
    title: str | None = None
    artist_id: str | None = Field(default=None, pattern=ARTIST_ID_PATTERN)
    medium: str | None = None
    dimensions: str | None = None
    creation_year: int | None = None
    # Select as runtime::text so Postgres returns HH:MM:SS instead of a Python timedelta.
    runtime: str | None = Field(default=None, pattern=RUNTIME_PATTERN)

class ArtworkUpdate(BaseModel):
    """PATCH body: only the fields being changed."""

    accession_number: str | None = Field(default=None, pattern=ACCESSION_NUMBER_PATTERN)
    title: str | None = None
    artist_id: str | None = Field(default=None, pattern=ARTIST_ID_PATTERN)
    medium: str | None = None
    dimensions: str | None = None
    creation_year: int | None = None
    runtime: str | None = Field(default=None, pattern=RUNTIME_PATTERN)

# Exhibitions (public.exhibitions, Exhibition.yaml)

class Exhibition(BaseModel):
    """An exhibition. Used for POST request bodies and for every exhibition response."""

    exhibition_id: str = Field(pattern=EXHIBITION_ID_PATTERN)
    exhibition_name: str | None = None
    curator: str | None = None
    type: str | None = None
    location: str | None = None
    # `date` accepts and returns ISO 8601 dates (YYYY-MM-DD), matching `format: date` in the spec.
    start_date: date | None = None
    end_date: date | None = None

class ExhibitionUpdate(BaseModel):
    """PATCH body: only the fields being changed."""

    exhibition_id: str | None = Field(default=None, pattern=EXHIBITION_ID_PATTERN)
    exhibition_name: str | None = None
    curator: str | None = None
    type: str | None = None
    location: str | None = None
    start_date: date | None = None
    end_date: date | None = None

# Lists (ArtistList.yaml, ArtworkList.yaml, ExhibitionList.yaml + Page.yaml)

# T stands in for Artist, Artwork, or Exhibition, so one ListResponse class covers all three:
# ListResponse[Artist] is the ArtistList shape, ListResponse[Artwork] the ArtworkList shape, etc.
T = TypeVar("T")

class Page(BaseModel):
    """Pagination details returned with every list (Page.yaml)."""

    endCursor: str | None
    startCursor: str | None
    hasNextPage: bool
    hasPrevPage: bool
    limit: int = Field(ge=1, le=100)
    total: int = Field(ge=0)

class ListResponse(BaseModel, Generic[T]):
    """The shape of every list endpoint's response: {object: "list", page: {...}, items: [...]}."""

    object: Literal["list"] = "list"
    page: Page
    items: list[T]

# Errors (Error.yaml, returned as application/problem+json)

class Problem(BaseModel):
    """An error response in the RFC 9457 "problem details" format that Error.yaml describes."""

    type: str = "about:blank"
    title: str
    status: int = Field(ge=100, lt=600)
    instance: str | None = None
    details: dict[str, Any] | None = None
