"""Per-user access: a private DuckDB connection that only contains the user's stores.

What it does: reads `config/users.yaml` and builds, for one user, a new in-memory DuckDB
connection whose tables carry the original names (`fact_sales`, `dim_store`, ...) but only
hold the rows of the stores that user may see. The connection is then locked down.

Why it exists: permissions must be enforced by the backend, never by the prompt (Decision 16:
refusal in the prompt failed on 3-6 of 24 security questions). Because the model's SQL runs
on this connection, it cannot return another region's rows, whatever it writes.

Where it sits in the pipeline: execution step (... -> validation -> USER CONNECTION ->
execution -> answer). The validator (`validator.py`) is the first layer, this module the
second; they do not depend on each other.

Design note: the data is COPIED (`CREATE TEMP TABLE ... AS SELECT ... FROM raw ...`) and the
`raw` database is then DETACHED, instead of creating filtered views over an attached `raw`.
With views the hidden database stays attached and `raw.main.fact_sales` remains reachable by
name from inside the connection; with copies it is gone, so even SQL that slips past the
validator cannot reach it. The price is the copy time at connection setup (measured in
`tests/test_access.py`).
"""

from pathlib import Path

import duckdb
import yaml
from pydantic import BaseModel, ConfigDict, model_validator

# Tables that every user sees completely: they hold no store-level facts.
SHARED_TABLES = ("dim_date", "dim_holiday", "dim_product", "fx_rate")
# Memory cap of a user connection. Why: a runaway cross join must fail, not take the machine.
DEFAULT_MEMORY_LIMIT = "2GB"


class AccessError(Exception):
    """The user is unknown or their configuration does not match the data."""


class UserAccess(BaseModel):
    """What one user may see.

    Attributes:
        region_ids: The regions (`dim_store.region_id`) the user may see.
        all_stores: True for a user without restriction. Exactly one of the two is used.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    region_ids: list[int] = []
    all_stores: bool = False

    @model_validator(mode="after")
    def _exactly_one_scope(self) -> "UserAccess":
        if self.all_stores == bool(self.region_ids):
            raise ValueError("set either all_stores: true or a non-empty region_ids list")
        return self


class UsersFile(BaseModel):
    """The whole `users.yaml`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    users: dict[str, UserAccess]


def load_users(path: Path) -> dict[str, UserAccess]:
    """Read and validate the users file.

    Args:
        path: Path of `users.yaml`.

    Returns:
        Access rules by user name.

    Raises:
        FileNotFoundError: If the file does not exist.
        pydantic.ValidationError: If the file does not match the model.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return UsersFile.model_validate(raw).users


def _quote_path(path: Path) -> str:
    """Quote a file path as a SQL string literal (ATTACH takes a literal, not a parameter)."""
    return "'" + str(path).replace("'", "''") + "'"


def open_user_connection(
    db_path: Path, access: UserAccess, memory_limit: str = DEFAULT_MEMORY_LIMIT
) -> duckdb.DuckDBPyConnection:
    """Build a locked-down connection that holds only the user's stores.

    Steps, in this order (the order matters, see the comments):
      1. new in-memory connection, `raw` attached READ_ONLY;
      2. temp table of the allowed store ids;
      3. temp tables with the original names, filtered by those stores, copied from `raw`;
      4. DETACH `raw`; 5. disable external access; 6. memory limit; 7. lock the configuration.

    Args:
        db_path: The DuckDB file with all data. It is never written (READ_ONLY attach).
        access: The user's access rule.
        memory_limit: DuckDB memory limit string, e.g. "2GB".

    Returns:
        An open connection. The caller must close it.

    Raises:
        AccessError: If the rule selects no store at all (a typo in `region_ids`).
    """
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"ATTACH {_quote_path(db_path)} AS raw (READ_ONLY)")
        if access.all_stores:
            store_filter = "SELECT store_id FROM raw.dim_store"
        else:
            ids = ", ".join(str(int(region_id)) for region_id in access.region_ids)
            # ids are ints (Pydantic + int()), never text from a user or a model.
            # ids are ints (Pydantic + int()), never text from a user or a model.
            store_filter = f"SELECT store_id FROM raw.dim_store WHERE region_id IN ({ids})"  # noqa: S608  # noqa: S608
        connection.execute(f"CREATE TEMP TABLE allowed_store AS {store_filter}")
        if connection.execute("SELECT count(*) FROM allowed_store").fetchone() == (0,):
            raise AccessError("the access rule selects no store")

        connection.execute(
            "CREATE TEMP TABLE dim_store AS "
            "SELECT * FROM raw.dim_store WHERE store_id IN (SELECT store_id FROM allowed_store)"
        )
        connection.execute(
            "CREATE TEMP TABLE fact_sales AS "
            "SELECT * FROM raw.fact_sales WHERE store_id IN (SELECT store_id FROM allowed_store)"
        )
        for table in SHARED_TABLES:
            # `table` comes from the constant SHARED_TABLES, not from input.
            # `table` comes from the constant SHARED_TABLES, not from input.
            connection.execute(f"CREATE TEMP TABLE {table} AS SELECT * FROM raw.{table}")  # noqa: S608  # noqa: S608
        # The helper table is not part of the schema the model may use.
        connection.execute("DROP TABLE allowed_store")

        # Order: DETACH first. After `enable_external_access=false` and the lock, nothing
        # can be attached or detached any more.
        connection.execute("DETACH raw")
        connection.execute("SET enable_external_access = false")
        connection.execute(f"SET memory_limit = '{memory_limit}'")
        connection.execute("SET lock_configuration = true")
    except Exception:
        connection.close()
        raise
    return connection
