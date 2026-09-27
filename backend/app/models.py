"""Pydantic models mirroring the schemas in openapi/components/schemas.

WHAT THIS FILE DOES
A model describes the shape of a piece of data: which fields it has and what type each datum
is. Each model matches a schema in `openapi/components/schemas`.

FastAPI uses these models in two directions:
- Requests: the JSON body of a POST or PATCH is checked against a model before any SQL runs,
  so a bad ID format or a non-number year gets a 400 error instead of reaching the database.
- Responses: every response is passed through a model (`response_model=` in the routers),
  which guarantees it has exactly the fields and types the spec promises.

Every non-ID field is optional because the matching database column allows NULL.
Field names match the database column names exactly, so database rows fit the models as-is.

HOW TO INTERPRET PYTHON
- `class Name(BaseModel):` defines a model. Each indented line below it is one field.
- `field_name: str` means the field holds text ("str" is short for string).
  `int` is a whole number, and `date` is a calendar date.
- `str | None` means "text, or None". None is Python's word for empty (null in JSON).
- `= None` gives a default: if the field isn't provided, it's empty. A field with no default,
  like `artist_id: str = Field(...)` below, is required.
- `Field(pattern=...)` adds a rule: the value must match that pattern.
"""

# IMPORTS
from datetime import date  # The type for calendar dates (YYYY-MM-DD).
from typing import Any, Generic, Literal, TypeVar  # Building blocks for type hints, explained below.

# Pydantic is the library that checks data against models. FastAPI uses it automatically.
from pydantic import BaseModel, Field

# ID FORMAT RULES
# These are "regular expressions": patterns describing what a valid value looks like.
# They're the same patterns as the ID parameters and schemas in openapi/components.
# How to read them: ^ means "start", $ means "end", [A-Z] is any capital letter,
# [0-9] is any digit, {4} means "exactly 4 of the previous thing", and \. is a literal period.
# The r before the quotes tells Python to treat backslashes as ordinary characters.
ARTIST_ID_PATTERN = r"^ART-[A-Z]{3}-[0-9]{4}$"          # e.g., ART-JST-0001
ACCESSION_NUMBER_PATTERN = r"^[0-9]{4}\.[0-9]{4}$"      # e.g., 2021.0001
EXHIBITION_ID_PATTERN = r"^EXH-[0-9]{4}$"               # e.g., EXH-0001
# HH:MM:SS, up to 23:59:59. The | means "or": the hour is 00-19 or 20-23.
RUNTIME_PATTERN = r"^([0-1][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9])$"

# ARTISTS (public.artists table, Artist.yaml)

class Artist(BaseModel):
    """An artist. Used for POST request bodies and for every artist response."""

    # Required, and must match the artist ID pattern.
    artist_id: str = Field(pattern=ARTIST_ID_PATTERN)
    # Optional text fields; empty (None) when not provided.
    artist_name: str | None = None
    birth_year: int | None = None
    death_year: int | None = None
    gender: str | None = None
    nationality: str | None = None
    based_in_place: str | None = None

class ArtistUpdate(BaseModel):
    """PATCH body: only the fields being changed.

    Every field is optional (even the ID) so a client can send just the fields it wants to change.
    """

    artist_id: str | None = Field(default=None, pattern=ARTIST_ID_PATTERN)
    artist_name: str | None = None
    birth_year: int | None = None
    death_year: int | None = None
    gender: str | None = None
    nationality: str | None = None
    based_in_place: str | None = None

# ARTWORKS (public.artworks table, Artwork.yaml)

class Artwork(BaseModel):
    """An artwork. Used for POST request bodies and for every artwork response."""

    accession_number: str = Field(pattern=ACCESSION_NUMBER_PATTERN)
    title: str | None = None
    # Optional, but if provided it must look like an artist ID.
    artist_id: str | None = Field(default=None, pattern=ARTIST_ID_PATTERN)
    medium: str | None = None
    dimensions: str | None = None
    creation_year: int | None = None
    # Stored in Postgres as an interval (a length of time). The routers convert it to text
    # (runtime::text in SQL) so it comes back as HH:MM:SS, e.g. "01:30:00".
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

# EXHIBITIONS (public.exhibitions table, Exhibition.yaml)

class Exhibition(BaseModel):
    """An exhibition. Used for POST request bodies and for every exhibition response."""

    exhibition_id: str = Field(pattern=EXHIBITION_ID_PATTERN)
    exhibition_name: str | None = None
    curator: str | None = None
    type: str | None = None
    location: str | None = None
    # `date` accepts and returns dates written as YYYY-MM-DD, matching `format: date` in the spec.
    # A value like "March 1" is rejected with a 400 error.
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

# LISTS (ArtistList.yaml, ArtworkList.yaml, ExhibitionList.yaml, and Page.yaml)

# T is a placeholder that stands for "some model", like a blank to fill in later.
# It lets one ListResponse model below cover all three list shapes:
# ListResponse[Artist] is the ArtistList shape, ListResponse[Artwork] is ArtworkList, and so on.
T = TypeVar("T")

class Page(BaseModel):
    """Pagination details returned with every list (Page.yaml)."""

    # These fields have no default, so every list response must include all of them.
    endCursor: str | None
    startCursor: str | None
    # `bool` is Boolean (true/false).
    hasNextPage: bool
    hasPrevPage: bool
    # ge= means "greater than or equal to", le= means "less than or equal to".
    limit: int = Field(ge=1, le=100)
    total: int = Field(ge=0)

# Generic[T] marks this model as having the fill-in-the-blank placeholder T described above.
class ListResponse(BaseModel, Generic[T]):
    """The shape of every list endpoint's response: {object: "list", page: {...}, items: [...]}."""

    # Literal["list"] means this field can only ever be the exact text "list".
    object: Literal["list"] = "list"
    page: Page
    # list[T] means "a list of T", e.g. a list of Artist objects.
    items: list[T]

# ERRORS (Error.yaml, returned as application/problem+json)

class Problem(BaseModel):
    """An error response in the "problem details" format (RFC 9457) that Error.yaml describes."""

    type: str = "about:blank"
    title: str
    # lt= means "less than", so status must be a valid HTTP status code from 100 to 599.
    status: int = Field(ge=100, lt=600)
    instance: str | None = None
    # dict[str, Any] means a dictionary (key/value pairs, like a JSON object) whose keys are
    # text and whose values can be anything.
    details: dict[str, Any] | None = None
