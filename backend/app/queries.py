"""SQL helpers shared by the routers: paginated lists with sort/filter/search, and simple CRUD.

All three routers list, get, add, update, and delete rows in the same way; only the table,
primary key, and columns differ. Keeping that logic here means each router just passes in
its own names, and a fix to sorting or pagination applies to every endpoint at once.

Safety: table and column names are only ever passed in by the routers, never taken from the
request, and are always quoted with sql.Identifier. Request values always go through %s
placeholders, which psycopg sends to Postgres separately from the SQL. Together, these prevent
SQL injection.
"""

import base64
import re
from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException
from psycopg import Connection, sql

# Matches `field:value` pairs, where a value may contain spaces (e.g. `location:Gallery 1`).
# A value ends where the next `word:` starts, or at the end of the string.
FILTER_PAIR = re.compile(r"(\w+):(.*?)(?=\s+\w+:|$)")

# Every query aliases its main table as `t`, so joined tables can't make column names ambiguous.
# (For example, both artists and exhibitions_artists have an artist_id column.)
ALL_COLUMNS = sql.SQL("t.*")


def column(name: str) -> sql.Identifier:
    """A column of the main table, written as t."name"."""
    return sql.Identifier("t", name)


# Pagination cursors (Page.yaml). Opaque to clients; internally they encode a row offset.
# Base64 keeps them opaque, as Page.yaml describes, so clients pass them back unchanged
# instead of relying on what's inside. That leaves room to change how cursors work later.

def encode_cursor(offset: int) -> str:
    """Turn a row position into a cursor string, e.g. 10 -> "MTA="."""
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def decode_cursor(cursor: str) -> int:
    """Turn a cursor string back into a row position, or return 400 if it's not a valid cursor."""
    try:
        offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
    except ValueError:
        raise HTTPException(400, "Invalid pagination cursor.")
    if offset < 0:
        raise HTTPException(400, "Invalid pagination cursor.")
    return offset


# Sort.yaml, Filter.yaml, Search.yaml

def build_order_by(sort: str | None, columns: Sequence[str], key: str, resource: str) -> sql.Composable:
    """Build the ORDER BY clause from the `sort` parameter (`title`, or `-title` for descending).

    Only columns in the router's allow-list are accepted; anything else returns 400.
    """
    name, direction = key, sql.SQL("ASC")
    if sort:
        name = sort.removeprefix("-")
        if name not in columns:
            raise HTTPException(400, f"Cannot sort {resource} by '{name}'.")
        if sort.startswith("-"):
            direction = sql.SQL("DESC")
    # Empty values go last in either direction, so they don't crowd the top of the list.
    # Always tie-break on the primary key so pages are stable: rows with the same sort value
    # always come back in the same order, so none are skipped or repeated between pages.
    return sql.SQL("ORDER BY {} {} NULLS LAST, {} ASC").format(column(name), direction, column(key))


def build_filter_and_search(
    filter: str | None,
    search: str | None,
    columns: Sequence[str],
    search_columns: Sequence[str],
    resource: str,
) -> tuple[list[sql.Composable], list[Any]]:
    """Turn the `filter` and `search` parameters into WHERE conditions and their values.

    - filter: `nationality:Canadian,American type:solo` -> exact matches, commas meaning OR,
      and every pair must match (AND).
    - search: a case-insensitive substring match across the router's text columns.
    """
    conditions: list[sql.Composable] = []
    params: list[Any] = []

    if filter:
        pairs = FILTER_PAIR.findall(filter.strip())
        if not pairs:
            raise HTTPException(400, "Filter must use field:value pairs.")
        for name, value in pairs:
            if name not in columns:
                raise HTTPException(400, f"Cannot filter {resource} by '{name}'.")
            # Compare as text so the same syntax works for text, integer, date, and interval columns.
            # Match the whole value too, so values containing commas (`Toronto, Canada`) still work.
            value = value.strip()
            conditions.append(sql.SQL("{}::text = ANY(%s)").format(column(name)))
            params.append([value, *(v.strip() for v in value.split(","))])

    if search:
        # ILIKE is Postgres's case-insensitive LIKE; %term% matches the term anywhere in the value.
        matches = [sql.SQL("{} ILIKE %s").format(column(name)) for name in search_columns]
        conditions.append(sql.SQL("({})").format(sql.SQL(" OR ").join(matches)))
        params.extend([f"%{search}%"] * len(search_columns))

    return conditions, params


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

    Every list endpoint calls this. The exhibition artists and artworks endpoints also pass
    `join` and `conditions` to limit the rows to those linked to one exhibition.
    """
    if after and before:
        raise HTTPException(400, "Use either 'after' or 'before', not both.")

    # `after` continues from the end of the previous page; `before` steps back one page.
    offset = 0
    if after:
        offset = decode_cursor(after)
    elif before:
        offset = max(decode_cursor(before) - limit, 0)

    extra_conditions, extra_params = build_filter_and_search(
        filter, search, columns, search_columns, resource
    )
    all_conditions = [*conditions, *extra_conditions]
    all_params = [*params, *extra_params]

    source = sql.SQL("FROM {} AS t").format(sql.Identifier(table))
    if join is not None:
        source = sql.SQL("{} {}").format(source, join)
    where = sql.SQL("")
    if all_conditions:
        where = sql.SQL("WHERE ") + sql.SQL(" AND ").join(all_conditions)

    # Page.yaml's `total` is the count across all pages, so count before applying LIMIT.
    total = conn.execute(
        sql.SQL("SELECT COUNT(*) AS total {} {}").format(source, where), all_params
    ).fetchone()["total"]

    rows = conn.execute(
        sql.SQL("SELECT {} {} {} {} LIMIT %s OFFSET %s").format(
            select, source, where, build_order_by(sort, columns, key, resource)
        ),
        [*all_params, limit, offset],
    ).fetchall()

    # The endpoint's response_model (ListResponse[...]) adds `object: "list"` and validates this.
    return {
        "page": {
            # Cursors are null on an empty page, as Page.yaml describes.
            "startCursor": encode_cursor(offset) if rows else None,
            "endCursor": encode_cursor(offset + len(rows)) if rows else None,
            "hasNextPage": offset + len(rows) < total,
            "hasPrevPage": offset > 0,
            "limit": limit,
            "total": total,
        },
        "items": rows,
    }


# Single-row CRUD (create, read, update, delete)

def get_row(
    conn: Connection, table: str, key: str, value: Any, select: sql.Composable = ALL_COLUMNS
) -> dict[str, Any] | None:
    """Fetch one row by primary key, or None if it doesn't exist."""
    return conn.execute(
        sql.SQL("SELECT {} FROM {} AS t WHERE {} = %s").format(
            select, sql.Identifier(table), column(key)
        ),
        [value],
    ).fetchone()


def require_row(conn: Connection, table: str, key: str, value: Any, label: str) -> None:
    """Raise 404 unless a row with this key exists."""
    # Selecting a constant is enough to check existence without fetching the whole row.
    if get_row(conn, table, key, value, sql.SQL("1 AS found")) is None:
        raise HTTPException(404, f"{label} not found.")


def insert_row(conn: Connection, table: str, data: dict[str, Any]) -> None:
    """Insert one row. `data` maps column names to values, e.g. from model_dump()."""
    # A duplicate key raises UniqueViolation, which errors.py turns into 409.
    conn.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, data)),
            sql.SQL(", ").join([sql.Placeholder()] * len(data)),
        ),
        list(data.values()),
    )


def update_row(conn: Connection, table: str, key: str, value: Any, data: dict[str, Any]) -> bool:
    """Update the given columns. Returns False if no row has this key."""
    # Only the columns in `data` are touched, which is what makes PATCH a partial update.
    cursor = conn.execute(
        sql.SQL("UPDATE {} SET {} WHERE {} = %s").format(
            sql.Identifier(table),
            sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(name)) for name in data),
            sql.Identifier(key),
        ),
        [*data.values(), value],
    )
    return cursor.rowcount > 0


def delete_row(conn: Connection, table: str, key: str, value: Any) -> bool:
    """Delete one row. Returns False if no row has this key."""
    # A row still referenced elsewhere raises RestrictViolation, which errors.py turns into 409.
    cursor = conn.execute(
        sql.SQL("DELETE FROM {} WHERE {} = %s").format(sql.Identifier(table), sql.Identifier(key)),
        [value],
    )
    return cursor.rowcount > 0
