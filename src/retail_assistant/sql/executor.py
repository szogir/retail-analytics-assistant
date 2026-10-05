"""SQL executor: runs a query with a timeout and a row limit.

What it does: opens the database read-only, runs one SQL statement, and returns the column
names and at most `row_limit` rows.

Why it exists: the SQL comes from a model, so it must not be able to run forever or return
millions of rows. (The safety checks that decide WHICH SQL may run live in
`validator.py` and `access.py`; this module only limits the cost of what does run.)

Where it sits in the pipeline: execution step (... -> validation -> execution -> answer).
"""

import threading
from dataclasses import dataclass
from pathlib import Path

import duckdb


class SqlExecutionError(Exception):
    """The SQL failed (syntax, unknown column, timeout, ...). The message is shown to the user."""


@dataclass(frozen=True)
class QueryResult:
    """A result table.

    Attributes:
        columns: Column names, in order.
        rows: The rows (at most `row_limit`).
        truncated: True if the query had more rows than the limit.
    """

    columns: list[str]
    rows: list[tuple[object, ...]]
    truncated: bool


def run_on_connection(
    connection: duckdb.DuckDBPyConnection, sql: str, row_limit: int, timeout_seconds: float
) -> QueryResult:
    """Run one statement on an already prepared connection, with timeout and row limit.

    Why a separate function: `execute_query` (full database, read-only file) and the per-user
    connection of `access.py` prepare their connection differently but must cap the cost of the
    statement in exactly the same way.

    Raises:
        SqlExecutionError: If the SQL fails or runs into the timeout.
    """
    # DuckDB has no query timeout setting, so a timer thread calls interrupt() instead.
    timer = threading.Timer(timeout_seconds, connection.interrupt)
    timer.start()
    try:
        cursor = connection.execute(sql)
        columns = [column[0] for column in cursor.description or []]
        # Fetch one row more than the limit to learn whether the result was cut off. This
        # also is the row limit of the validated path: the query text is never rewritten.
        fetched = cursor.fetchmany(row_limit + 1)
    except duckdb.Error as exc:
        raise SqlExecutionError(str(exc)) from exc
    finally:
        timer.cancel()
    return QueryResult(
        columns=columns, rows=fetched[:row_limit], truncated=len(fetched) > row_limit
    )


def execute_query(
    db_path: Path, sql: str, row_limit: int = 1000, timeout_seconds: float = 30.0
) -> QueryResult:
    """Run one SQL statement read-only.

    Args:
        db_path: The DuckDB file.
        sql: The statement.
        row_limit: Maximum number of rows returned.
        timeout_seconds: The query is interrupted after this many seconds.

    Returns:
        The columns and rows.

    Raises:
        SqlExecutionError: If the SQL fails or runs into the timeout.
    """
    # Design note: read_only=True means even a DELETE or DROP the model might write fails
    # at the engine level. The alternative, trusting the prompt to forbid writes, is exactly
    # what this project avoids: permissions belong to the backend.
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        # Design note: read_only protects the database file, but not the machine: without this
        # setting model SQL could still call read_csv('/etc/passwd') or COPY ... TO 'file'.
        # The validator blocks these in the SQL text as well (two independent layers).
        connection.execute("SET enable_external_access = false")
        return run_on_connection(connection, sql, row_limit, timeout_seconds)
    finally:
        connection.close()
