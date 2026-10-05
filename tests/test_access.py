"""Tests of the per-user connection, on the installed DuckDB version.

The tests prove the properties that the security story relies on: the filtered data, the
lock on the settings, the absence of the `raw` database, and an untouched database file.
"""

# The f-strings below only insert module constants (region and store ids), never input.
# ruff: noqa: S608

import time
from pathlib import Path

import duckdb
import pytest

from evals.provenance import file_hash
from retail_assistant.config import PROJECT_ROOT
from retail_assistant.sql.access import (
    AccessError,
    UserAccess,
    load_users,
    open_user_connection,
)
from retail_assistant.sql.executor import SqlExecutionError, run_on_connection
from retail_assistant.sql.validator import ALLOWED_TABLES

USERS_PATH = PROJECT_ROOT / "config" / "users.yaml"
# Region 3 = Dél-Alföld. The only test store (store 4) is in region 1, Budapest.
ANNA_REGION = 3
TEST_STORE_ID = 4

SAME_SQL = "SELECT count(*), sum(gross_amount) FROM fact_sales"


def user(name: str) -> UserAccess:
    return load_users(USERS_PATH)[name]


def scalar(connection: duckdb.DuckDBPyConnection, sql: str) -> object:
    row = connection.execute(sql).fetchone()
    assert row is not None
    return row[0]


# --- users file ----------------------------------------------------------------------------


def test_users_file_has_anna_with_one_hungarian_region_and_carla_with_everything() -> None:
    users = load_users(USERS_PATH)
    assert users["anna"] == UserAccess(region_ids=[ANNA_REGION])
    assert users["carla"] == UserAccess(all_stores=True)


def test_anna_region_is_hungarian_and_the_test_store_is_elsewhere(full_db_path: Path) -> None:
    connection = duckdb.connect(str(full_db_path), read_only=True)
    try:
        countries = connection.execute(
            f"SELECT DISTINCT country_code FROM dim_store WHERE region_id = {ANNA_REGION}"
        ).fetchall()
        test_region = scalar(connection, "SELECT region_id FROM dim_store WHERE is_test_store")
    finally:
        connection.close()
    assert countries == [("HU",)]
    assert test_region != ANNA_REGION


@pytest.mark.parametrize(
    "fields", [{}, {"all_stores": True, "region_ids": [3]}, {"all_stores": False}]
)
def test_a_user_needs_exactly_one_scope(fields: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        UserAccess(**fields)  # type: ignore[arg-type]


def test_a_rule_without_matching_stores_is_an_error(full_db_path: Path) -> None:
    with pytest.raises(AccessError):
        open_user_connection(full_db_path, UserAccess(region_ids=[999]))


# --- filtering -----------------------------------------------------------------------------


def test_anna_and_carla_get_different_numbers_for_the_same_sql(full_db_path: Path) -> None:
    results: dict[str, tuple[object, ...]] = {}
    for name in ("anna", "carla"):
        connection = open_user_connection(full_db_path, user(name))
        try:
            row = connection.execute(SAME_SQL).fetchone()
            assert row is not None
            results[name] = row
        finally:
            connection.close()
    assert results["anna"] != results["carla"]
    anna_count, carla_count = results["anna"][0], results["carla"][0]
    assert isinstance(anna_count, int) and isinstance(carla_count, int)
    assert anna_count < carla_count


def test_annas_result_equals_an_independent_hand_written_regional_query(
    full_db_path: Path,
) -> None:
    # The reference does not use access.py: it reads the full database directly and filters
    # by region in the WHERE clause, written by hand.
    reference_sql = f"""
        SELECT s.store_id, count(*), sum(f.gross_amount), sum(f.quantity)
        FROM fact_sales f JOIN dim_store s ON s.store_id = f.store_id
        WHERE s.region_id = {ANNA_REGION}
        GROUP BY s.store_id ORDER BY s.store_id"""
    scoped_sql = """
        SELECT s.store_id, count(*), sum(f.gross_amount), sum(f.quantity)
        FROM fact_sales f JOIN dim_store s ON s.store_id = f.store_id
        GROUP BY s.store_id ORDER BY s.store_id"""
    full = duckdb.connect(str(full_db_path), read_only=True)
    try:
        expected = full.execute(reference_sql).fetchall()
    finally:
        full.close()
    connection = open_user_connection(full_db_path, user("anna"))
    try:
        actual = connection.execute(scoped_sql).fetchall()
        stores = connection.execute("SELECT store_id FROM dim_store ORDER BY 1").fetchall()
    finally:
        connection.close()
    assert actual == expected
    assert len(expected) == 3
    assert [row[0] for row in stores] == [8, 9, 10]


def test_the_connection_only_scopes_and_applies_no_business_rule(full_db_path: Path) -> None:
    carla = open_user_connection(full_db_path, user("carla"))
    anna = open_user_connection(full_db_path, user("anna"))
    full = duckdb.connect(str(full_db_path), read_only=True)
    try:
        cancelled = "SELECT count(*) FROM fact_sales WHERE is_cancelled"
        returns = "SELECT count(*) FROM fact_sales WHERE is_return"
        # Carla's copy is identical to the database: cancelled rows and returns are kept.
        assert scalar(carla, cancelled) == scalar(full, cancelled)
        assert scalar(carla, returns) == scalar(full, returns)
        # The test store stays visible for carla, and is outside anna's scope.
        in_store = f"SELECT count(*) FROM fact_sales WHERE store_id = {TEST_STORE_ID}"
        assert scalar(carla, in_store) == scalar(full, in_store)
        assert scalar(anna, in_store) == 0
        # Anna's cancelled rows are exactly her stores' cancelled rows, not "none".
        expected = scalar(
            full,
            "SELECT count(*) FROM fact_sales f JOIN dim_store s USING (store_id) "
            f"WHERE f.is_cancelled AND s.region_id = {ANNA_REGION}",
        )
        assert scalar(anna, cancelled) == expected
        assert isinstance(expected, int) and expected > 0
    finally:
        for connection in (carla, anna, full):
            connection.close()


def test_the_connection_offers_exactly_the_allowed_tables(full_db_path: Path) -> None:
    connection = open_user_connection(full_db_path, user("anna"))
    try:
        names = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    finally:
        connection.close()
    assert names == set(ALLOWED_TABLES)


# --- the raw database is really gone -------------------------------------------------------


def test_raw_is_not_attached_after_setup(full_db_path: Path) -> None:
    connection = open_user_connection(full_db_path, user("carla"))
    try:
        rows = connection.execute("SELECT database_name FROM duckdb_databases()").fetchall()
        assert "raw" not in {row[0] for row in rows}
        for sql in (
            "SELECT * FROM raw.main.fact_sales",
            "SELECT * FROM raw.fact_sales",
            "SELECT * FROM raw.dim_store",
        ):
            with pytest.raises(duckdb.Error):
                connection.execute(sql)
        # Attaching it again is impossible: external access is off.
        with pytest.raises(duckdb.Error):
            connection.execute(f"ATTACH '{full_db_path}' AS raw (READ_ONLY)")
    finally:
        connection.close()


# --- the settings cannot be overwritten ----------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SET enable_external_access = true",
        "SET lock_configuration = false",
        "SET memory_limit = '100GB'",
        "RESET enable_external_access",
        "RESET memory_limit",
        "PRAGMA enable_external_access = true",
        "SELECT * FROM read_text('C:/Windows/win.ini')",
        "COPY (SELECT 1) TO 'leak_from_access_test.csv'",
        "INSTALL httpfs",
    ],
)
def test_settings_are_locked_and_files_are_unreachable(full_db_path: Path, sql: str) -> None:
    connection = open_user_connection(full_db_path, user("anna"))
    try:
        with pytest.raises(duckdb.Error):
            connection.execute(sql)
        assert scalar(connection, "SELECT current_setting('enable_external_access')") is False
    finally:
        connection.close()
    assert not Path("leak_from_access_test.csv").exists()


def test_memory_limit_is_set(full_db_path: Path) -> None:
    connection = open_user_connection(full_db_path, user("anna"), memory_limit="1GB")
    try:
        limit = str(scalar(connection, "SELECT current_setting('memory_limit')"))
    finally:
        connection.close()
    assert limit.startswith("953")  # 1GB = 10^9 bytes = 953.6 MiB


# --- cost and file integrity ---------------------------------------------------------------


def test_setup_time_per_user_is_under_two_seconds(
    full_db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Decision rule: the copy-and-detach variant is used only if setup stays under 2 s."""
    timings: dict[str, float] = {}
    for name in ("anna", "carla"):
        started = time.perf_counter()
        open_user_connection(full_db_path, user(name)).close()
        timings[name] = time.perf_counter() - started
    with capsys.disabled():
        print(f"\nSETUP seconds per user: { ({k: round(v, 2) for k, v in timings.items()}) }")
    assert max(timings.values()) < 2.0


def test_the_database_file_is_unchanged_by_setup_and_use(full_db_path: Path) -> None:
    before = file_hash(full_db_path)
    connection = open_user_connection(full_db_path, user("carla"))
    try:
        connection.execute(SAME_SQL).fetchall()
        # Even a write inside the user's own copy must not reach the file.
        connection.execute("DELETE FROM fact_sales")
    finally:
        connection.close()
    assert file_hash(full_db_path) == before


def test_run_on_connection_limits_rows(full_db_path: Path) -> None:
    connection = open_user_connection(full_db_path, user("anna"))
    try:
        result = run_on_connection(connection, "SELECT * FROM fact_sales", 5, 30.0)
        with pytest.raises(SqlExecutionError):
            run_on_connection(connection, "SELECT nope FROM fact_sales", 5, 30.0)
    finally:
        connection.close()
    assert len(result.rows) == 5 and result.truncated
