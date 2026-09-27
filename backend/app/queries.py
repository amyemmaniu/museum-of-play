"""SQL helpers shared by the routers: paginated lists with sort/filter/search, and simple CRUD.

WHAT THIS FILE DOES
All three routers (artists, artworks, exhibitions) list, get, add, update, and delete rows in
the same way. Only the table name, primary key, and column names differ. Rather than repeat
the same code three times, it lives here, and each router passes in its own names.
A fix to sorting or pagination here applies to every endpoint at once.

"CRUD" stands for Create, Read, Update, Delete: the four basic things you do with a record.

SAFETY: PREVENTING SQL INJECTION
SQL injection is an attack where someone sends text that gets run as part of a database query.
This file prevents it in two ways:
- Table and column names only ever come from the routers' fixed lists, never from the request,
  and are wrapped in sql.Identifier, which quotes them safely.
- Values from the request (search terms, IDs, etc.) always go through %s placeholders.
  psycopg sends them to Postgres separately from the SQL text, so they're treated as data,
  never as commands.

HOW TO INTERPRET PYTHON
- `def name(inputs) -> OutputType:` defines a function. `-> bool` means it returns
  True or False; `-> None` means it returns nothing.
- `x: str | None = None` in a function's inputs means x is optional text, empty by default.
- A `*` on its own in a function's inputs means every input after it must be passed by name,
  e.g. list_page(conn, table="artists", key="artist_id", ...). This makes calls easier to read.
- `[a, b, c]` is a list (an ordered collection). `{"key": value}` is a dictionary
  (key/value pairs, like a JSON object).
- `[*a, *b]` builds one list containing everything in list a followed by everything in list b.
- `raise HTTPException(400, "message")` stops and sends an error response.
  errors.py turns it into the problem+json format.
"""

# IMPORTS
import base64  # Encodes numbers into short text strings, used for pagination cursors.
import re  # Regular expressions: patterns for finding text, used to parse the `filter` parameter.
from collections.abc import Sequence  # Used in type hints to mean "a list or similar collection".
from typing import Any  # Used in type hints to mean "any kind of value".

from fastapi import HTTPException  # Used to stop and return an error response.
# psycopg talks to Postgres. `sql` is its tool for building queries safely out of pieces.
from psycopg import Connection, sql

# A pattern that finds `field:value` pairs in the filter text, where a value may contain
# spaces (e.g. `location:Gallery 1`). A value ends where the next `word:` starts, or at the
# end of the text. re.compile prepares the pattern once so it can be reused quickly.
FILTER_PAIR = re.compile(r"(\w+):(.*?)(?=\s+\w+:|$)")

# Every query gives its main table the short nickname `t` (e.g. FROM artists AS t).
# This avoids confusion when two joined tables have a column with the same name.
# (For example, both artists and exhibitions_artists have an artist_id column.)
# "t.*" means "every column of t".
ALL_COLUMNS = sql.SQL("t.*")

def column(name: str) -> sql.Identifier:
    """Refer to a column of the main table safely, written in SQL as t."name"."""
    return sql.Identifier("t", name)

# PAGINATION CURSORS (Page.yaml)
# A list is returned one page at a time. A "cursor" is a bookmark the client passes back to
# get the next or previous page. Internally it's just a row position (e.g. "start at row 10"),
# encoded with base64 so it looks like random text (10 becomes "MTA=").
# Page.yaml says cursors are "opaque": clients should pass them back unchanged rather than
# build their own. That leaves room to change how cursors work later without breaking clients.

def encode_cursor(offset: int) -> str:
    """Turn a row position into a cursor string, e.g. 10 -> "MTA="."""
    # str(offset) turns the number into text, .encode() into bytes, base64 encodes those bytes,
    # and .decode() turns the result back into ordinary text.
    return base64.urlsafe_b64encode(str(offset).encode()).decode()

def decode_cursor(cursor: str) -> int:
    """Turn a cursor string back into a row position, or return 400 if it's not a valid cursor."""
    # `try:` runs the indented code; if it fails with the error named in `except`,
    # the `except` block runs instead of the whole request crashing.
    try:
        # The reverse of encode_cursor; int(...) turns the text back into a number.
        offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
    except ValueError:
        # The cursor wasn't valid base64 or didn't contain a number.
        raise HTTPException(400, "Invalid pagination cursor.")
    # A negative row position makes no sense, so reject it too.
    if offset < 0:
        raise HTTPException(400, "Invalid pagination cursor.")
    return offset

# SORTING, FILTERING, AND SEARCHING (Sort.yaml, Filter.yaml, Search.yaml)

def build_order_by(sort: str | None, columns: Sequence[str], key: str, resource: str) -> sql.Composable:
    """Build the SQL ORDER BY clause from the `sort` parameter.

    `sort=title` sorts A to Z; `sort=-title` (with a minus sign) sorts Z to A.
    Only columns in the router's allowed list are accepted; anything else returns 400.

    Inputs: the sort text from the request (or None), the allowed columns, the table's primary
    key (the default sort), and the resource name for error messages (e.g. "artists").
    """
    # By default, sort by the primary key in ascending (A to Z, low to high) order.
    # This line sets two variables at once: name = key, direction = ASC.
    name, direction = key, sql.SQL("ASC")
    # Only change the default if a sort was requested.
    if sort:
        # Remove a leading "-" if there is one, leaving just the column name.
        name = sort.removeprefix("-")
        # `not in` checks that the name is NOT in the allowed list.
        if name not in columns:
            raise HTTPException(400, f"Cannot sort {resource} by '{name}'.")
        # A leading "-" means descending (Z to A, high to low).
        if sort.startswith("-"):
            direction = sql.SQL("DESC")
    # Build the clause. Each {} is filled in, in order, by the values given to .format(...).
    # NULLS LAST: empty values go at the end in either direction, so they don't crowd the top.
    # The final ", <key> ASC" is a tie-breaker: rows with the same sort value always come back in
    # the same order, so no row is skipped or repeated when moving between pages.
    return sql.SQL("ORDER BY {} {} NULLS LAST, {} ASC").format(column(name), direction, column(key))

def build_filter_and_search(
    filter: str | None,
    search: str | None,
    columns: Sequence[str],
    search_columns: Sequence[str],
    resource: str,
) -> tuple[list[sql.Composable], list[Any]]:
    """Turn the `filter` and `search` parameters into SQL WHERE conditions and their values.

    - filter: `nationality:Canadian,American type:solo` means exact matches, commas mean OR
      (Canadian or American), and every pair must match (AND).
    - search: a case-insensitive "contains" match across the router's text columns.

    Returns two lists that line up with each other: the SQL conditions (with %s placeholders)
    and the values that fill those placeholders. `tuple[...]` means it returns both together.
    """
    # Start with two empty lists and add to them below.
    conditions: list[sql.Composable] = []
    params: list[Any] = []

    # FILTER
    if filter:
        # Find every `field:value` pair. Each pair comes back as (field, value).
        # .strip() removes spaces from the start and end of the text.
        pairs = FILTER_PAIR.findall(filter.strip())
        # If nothing looked like field:value, the filter is malformed.
        if not pairs:
            raise HTTPException(400, "Filter must use field:value pairs.")
        # `for name, value in pairs:` repeats the indented block once for each pair,
        # with `name` and `value` set to that pair's field and value.
        for name, value in pairs:
            if name not in columns:
                raise HTTPException(400, f"Cannot filter {resource} by '{name}'.")
            value = value.strip()
            # SQL: <column>::text = ANY(%s)
            # ::text converts the column to text first, so the same syntax works for text,
            # number, date, and interval columns. ANY(%s) means "equals any value in this list".
            conditions.append(sql.SQL("{}::text = ANY(%s)").format(column(name)))
            # The list of accepted values: the whole value as typed, plus each comma-separated
            # part. Including the whole value means values that contain commas, like
            # `Toronto, Canada`, still match.
            # `(v.strip() for v in value.split(","))` splits the text at each comma and trims
            # the spaces around every piece.
            params.append([value, *(v.strip() for v in value.split(","))])

    # SEARCH
    if search:
        # Build one "<column> ILIKE %s" condition per searchable column.
        # ILIKE is Postgres's case-insensitive text match.
        # `[... for name in search_columns]` builds a list by repeating the expression once per column.
        matches = [sql.SQL("{} ILIKE %s").format(column(name)) for name in search_columns]
        # Join them with OR (a match in any column counts) and wrap them in parentheses.
        conditions.append(sql.SQL("({})").format(sql.SQL(" OR ").join(matches)))
        # %term% means "contains term anywhere". One copy is needed per column's placeholder.
        params.extend([f"%{search}%"] * len(search_columns))

    return conditions, params

# THE MAIN LIST FUNCTION

def list_page(
    conn: Connection,
    *,
    table: str,
    key: str,
    columns: Sequence[str],
    resource: str,
    select: sql.Composable = ALL_COLUMNS,
    join: sql.Composable | None = None,
    conditions: Sequence[sql.Composable] = (),
    params: Sequence[Any] = (),
    search_columns: Sequence[str] = (),
    after: str | None = None,
    before: str | None = None,
    sort: str | None = None,
    filter: str | None = None,
    search: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Run a paginated list query and return it in the ListResponse shape.

    Every list endpoint calls this. The inputs are:
    - conn: the database connection.
    - table, key, columns, search_columns, resource: which table to read, its primary key,
      which columns can be sorted/filtered and searched, and a name for error messages.
    - select: which columns to return (every column unless a router says otherwise).
    - join, conditions, params: optional extra SQL. The exhibition artists and artworks
      endpoints use these to keep only the rows linked to one exhibition.
    - after, before, sort, filter, search, limit: the query parameters from the request.
    """
    # Only one direction of paging makes sense at a time.
    if after and before:
        raise HTTPException(400, "Use either 'after' or 'before', not both.")

    # WORK OUT WHICH ROW THE PAGE STARTS AT
    # Start at the first row (row 0) unless a cursor says otherwise.
    offset = 0
    if after:
        # `after` continues from the end of the previous page.
        offset = decode_cursor(after)
    # `elif` means "else if": only checked when the `if` above was false.
    elif before:
        # `before` steps back one page. max(..., 0) keeps it from going below row 0.
        offset = max(decode_cursor(before) - limit, 0)

    # COMBINE ALL THE CONDITIONS
    extra_conditions, extra_params = build_filter_and_search(
        filter, search, columns, search_columns, resource
    )
    all_conditions = [*conditions, *extra_conditions]
    all_params = [*params, *extra_params]

    # BUILD THE PIECES OF THE QUERY
    # FROM <table> AS t, plus the JOIN if one was given.
    source = sql.SQL("FROM {} AS t").format(sql.Identifier(table))
    if join is not None:
        source = sql.SQL("{} {}").format(source, join)
    # WHERE <condition> AND <condition> ..., or nothing if there are no conditions.
    where = sql.SQL("")
    if all_conditions:
        where = sql.SQL("WHERE ") + sql.SQL(" AND ").join(all_conditions)

    # COUNT THE MATCHING ROWS
    # Page.yaml's `total` is the count across all pages, so count before limiting to one page.
    # .fetchone() gets the single result row; ["total"] reads its "total" column.
    total = conn.execute(
        sql.SQL("SELECT COUNT(*) AS total {} {}").format(source, where), all_params
    ).fetchone()["total"]

    # FETCH ONE PAGE OF ROWS
    # LIMIT: at most `limit` rows. OFFSET: skip the first `offset` rows.
    # .fetchall() gets every result row as a list of dictionaries.
    rows = conn.execute(
        sql.SQL("SELECT {} {} {} {} LIMIT %s OFFSET %s").format(
            select, source, where, build_order_by(sort, columns, key, resource)
        ),
        [*all_params, limit, offset],
    ).fetchall()

    # RETURN THE RESULT
    # This dictionary has the same shape as ArtistList.yaml and the others.
    # The endpoint's response_model (ListResponse[...]) adds `object: "list"` and checks it.
    return {
        "page": {
            # `x if condition else None` means: use x when the condition is true, otherwise None.
            # Cursors are null on an empty page, as Page.yaml describes.
            "startCursor": encode_cursor(offset) if rows else None,
            "endCursor": encode_cursor(offset + len(rows)) if rows else None,
            # len(rows) is how many rows this page has. There's a next page if the rows seen so
            # far are fewer than the total.
            "hasNextPage": offset + len(rows) < total,
            "hasPrevPage": offset > 0,
            "limit": limit,
            "total": total,
        },
        "items": rows,
    }

# SINGLE-ROW CRUD (create, read, update, delete one record)

def get_row(
    conn: Connection, table: str, key: str, value: Any, select: sql.Composable = ALL_COLUMNS
) -> dict[str, Any] | None:
    """Read one row by its primary key. Returns the row as a dictionary, or None if it doesn't exist."""
    # SQL: SELECT <columns> FROM <table> AS t WHERE t.<key> = <value>
    return conn.execute(
        sql.SQL("SELECT {} FROM {} AS t WHERE {} = %s").format(
            select, sql.Identifier(table), column(key)
        ),
        [value],
    ).fetchone()

def require_row(conn: Connection, table: str, key: str, value: Any, label: str) -> None:
    """Stop with a 404 error unless a row with this key exists.

    `label` names the record in the error message, e.g. "Exhibition not found."
    """
    # Selecting a constant ("1") is enough to check that the row exists, without fetching all of it.
    # `is None` means no row was found.
    if get_row(conn, table, key, value, sql.SQL("1 AS found")) is None:
        raise HTTPException(404, f"{label} not found.")

def insert_row(conn: Connection, table: str, data: dict[str, Any]) -> None:
    """Create one row. `data` maps column names to values, e.g. {"artist_id": "ART-JST-0001", ...}."""
    # SQL: INSERT INTO <table> (<col1>, <col2>, ...) VALUES (%s, %s, ...)
    # There's one %s placeholder per column, filled in order by the values.
    # A duplicate primary key makes Postgres raise UniqueViolation, which errors.py turns into 409.
    conn.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table),
            # Each column name, safely quoted and separated by commas.
            sql.SQL(", ").join(map(sql.Identifier, data)),
            # As many %s placeholders as there are columns.
            sql.SQL(", ").join([sql.Placeholder()] * len(data)),
        ),
        list(data.values()),
    )

def update_row(conn: Connection, table: str, key: str, value: Any, data: dict[str, Any]) -> bool:
    """Change the given columns of one row. Returns False if no row has this key."""
    # SQL: UPDATE <table> SET <col1> = %s, <col2> = %s WHERE <key> = %s
    # Only the columns in `data` are changed, which is what makes PATCH a partial update.
    cursor = conn.execute(
        sql.SQL("UPDATE {} SET {} WHERE {} = %s").format(
            sql.Identifier(table),
            sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(name)) for name in data),
            sql.Identifier(key),
        ),
        # The new values, in the same order as the columns, followed by the key for WHERE.
        [*data.values(), value],
    )
    # rowcount is how many rows were changed; 0 means no row had this key.
    return cursor.rowcount > 0

def delete_row(conn: Connection, table: str, key: str, value: Any) -> bool:
    """Delete one row. Returns False if no row has this key."""
    # SQL: DELETE FROM <table> WHERE <key> = %s
    # A row that other rows still point to makes Postgres raise RestrictViolation,
    # which errors.py turns into 409.
    cursor = conn.execute(
        sql.SQL("DELETE FROM {} WHERE {} = %s").format(sql.Identifier(table), sql.Identifier(key)),
        [value],
    )
    return cursor.rowcount > 0
