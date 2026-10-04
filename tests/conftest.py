"""Shared pytest fixtures."""

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from data_gen.generate import build_database


@pytest.fixture(scope="session")
def full_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the complete synthetic database once per test session (a few seconds)."""
    db_path = tmp_path_factory.mktemp("retail") / "retail.duckdb"
    build_database(db_path)
    return db_path


@pytest.fixture
def db(full_db_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    """A read-only connection to the full database."""
    connection = duckdb.connect(str(full_db_path), read_only=True)
    yield connection
    connection.close()


@pytest.fixture
def tiny_db(tmp_path: Path) -> Path:
    """A very small database (two tables) for tests that do not need the full dataset."""
    path = tmp_path / "tiny.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("CREATE TABLE dim_store (store_id INTEGER, store_name VARCHAR)")
    connection.execute("INSERT INTO dim_store VALUES (1, 'A'), (2, 'B'), (3, 'C')")
    connection.execute(
        "CREATE TABLE fx_rate (rate_date DATE, currency VARCHAR, eur_rate DECIMAL(10,2))"
    )
    connection.close()
    return path
