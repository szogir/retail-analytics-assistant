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
