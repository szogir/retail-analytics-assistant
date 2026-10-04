"""Tests for the dimension tables produced by data_gen.generate.

The tests check the properties the rest of the project relies on: a deterministic
database, a test store to exclude (trap 2), enough HU stores per region for the
permission demo, correct fiscal calendar conventions and matching EN/HU names.
"""

import datetime as dt
from pathlib import Path

import duckdb
import numpy as np
import pytest

from data_gen.dimensions import (
    DATA_DAYS,
    DATA_END,
    DATA_START,
    SEED,
    build_dim_date,
    build_dim_product,
    build_dim_store,
    fiscal_year_start,
)
from data_gen.generate import build_database

SHORT_WINDOW_START = dt.date(2025, 3, 1)
SHORT_WINDOW_DAYS = 30  # keeps the database tests fast


def read_table(db_path: Path, table: str) -> list[tuple[object, ...]]:
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        # `table` comes from this test file, never from user input.
        return connection.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall()  # noqa: S608
    finally:
        connection.close()


# --- dim_date -----------------------------------------------------------------------


def test_dim_date_covers_the_whole_period_with_unique_days() -> None:
    rows = build_dim_date()
    assert len(rows) == DATA_DAYS
    assert len({row.date for row in rows}) == DATA_DAYS
    assert rows[0].date == dt.date(2023, 3, 1)
    assert rows[-1].date == DATA_END == dt.date(2026, 10, 3)


def test_last_fiscal_year_is_incomplete() -> None:
    rows = build_dim_date()
    assert rows[-1].fiscal_year == 2026
    assert rows[-1].fiscal_month == 8  # October is the 8th month of a March-based year
    assert DATA_START.month == 3 and DATA_START.day == 1  # starts on a fiscal year start


def test_fiscal_year_starts_on_first_of_march() -> None:
    assert fiscal_year_start(dt.date(2025, 3, 1)) == dt.date(2025, 3, 1)
    assert fiscal_year_start(dt.date(2026, 2, 28)) == dt.date(2025, 3, 1)
    assert fiscal_year_start(dt.date(2026, 3, 1)) == dt.date(2026, 3, 1)


def test_fiscal_attributes_differ_from_calendar() -> None:
    by_date = {row.date: row for row in build_dim_date()}

    first_day = by_date[dt.date(2025, 3, 1)]
    assert (first_day.fiscal_year, first_day.fiscal_month, first_day.fiscal_week) == (2025, 1, 1)

    # January 2026 belongs to fiscal year 2025, as its 11th month.
    january = by_date[dt.date(2026, 1, 15)]
    assert (january.fiscal_year, january.fiscal_month) == (2025, 11)

    last_day = by_date[dt.date(2026, 2, 28)]
    assert (last_day.fiscal_month, last_day.fiscal_week) == (12, 53)


def test_weekday_names_are_english() -> None:
    by_date = {row.date: row for row in build_dim_date()}
    assert by_date[dt.date(2025, 3, 1)].weekday == "Saturday"
    assert by_date[dt.date(2025, 3, 3)].weekday == "Monday"


# --- dim_store ----------------------------------------------------------------------


def test_dim_store_has_20_stores_in_two_countries() -> None:
    stores = build_dim_store()
    assert len(stores) == 20
    assert {s.country_code for s in stores} == {"HU", "AT"}
    assert [s.store_id for s in stores] == list(range(1, 21))


def test_exactly_one_test_store() -> None:
    test_stores = [s for s in build_dim_store() if s.is_test_store]
    assert len(test_stores) == 1


def test_every_hu_region_has_at_least_two_real_stores() -> None:
    # The permission demo scopes a user to one HU region; it needs a meaningful slice.
    real_hu = [s for s in build_dim_store() if s.country_code == "HU" and not s.is_test_store]
    stores_per_region: dict[int, int] = {}
    for store in real_hu:
        stores_per_region[store.region_id] = stores_per_region.get(store.region_id, 0) + 1
    assert len(stores_per_region) >= 3
    assert min(stores_per_region.values()) >= 2


def test_region_id_maps_to_one_region_name() -> None:
    names_per_region: dict[int, set[str]] = {}
    for store in build_dim_store():
        names_per_region.setdefault(store.region_id, set()).add(store.region_name)
    assert all(len(names) == 1 for names in names_per_region.values())


# --- dim_product --------------------------------------------------------------------


def test_dim_product_size_and_uniqueness() -> None:
    products = build_dim_product(np.random.default_rng(SEED))
    assert 150 <= len(products) <= 250
    assert len({p.product_id for p in products}) == len(products)
    assert len({p.name_en for p in products}) == len(products)


def test_every_product_has_names_in_both_languages() -> None:
    for product in build_dim_product(np.random.default_rng(SEED)):
        assert product.name_en.strip()
        assert product.name_hu.strip()
        assert product.category_en.strip()
        assert product.category_hu.strip()


def test_private_label_share_and_cheaper_price() -> None:
    products = build_dim_product(np.random.default_rng(SEED))
    private = [p for p in products if p.is_private_label]
    assert len(private) == len(products) // 2
    branded_by_name = {p.name_en.rsplit(" (", 1)[0]: p for p in products if not p.is_private_label}
    for product in private:
        twin = branded_by_name[product.name_en.rsplit(" (", 1)[0]]
        assert product.base_price_eur <= twin.base_price_eur


def test_prices_are_positive_multiples_of_five_cents() -> None:
    for product in build_dim_product(np.random.default_rng(SEED)):
        assert product.base_price_eur > 0
        assert product.base_price_eur * 20 == pytest.approx(round(product.base_price_eur * 20))


# --- determinism and database output ------------------------------------------------


def test_same_seed_gives_identical_products() -> None:
    first = build_dim_product(np.random.default_rng(SEED))
    second = build_dim_product(np.random.default_rng(SEED))
    assert first == second


def test_two_runs_write_identical_tables(tmp_path: Path) -> None:
    first_db = tmp_path / "first.duckdb"
    second_db = tmp_path / "second.duckdb"
    build_database(first_db, SHORT_WINDOW_START, SHORT_WINDOW_DAYS)
    build_database(second_db, SHORT_WINDOW_START, SHORT_WINDOW_DAYS)
    for table in ("dim_date", "dim_store", "dim_product", "dim_holiday", "fx_rate", "fact_sales"):
        assert read_table(first_db, table) == read_table(second_db, table)


def test_written_database_has_expected_row_counts(tmp_path: Path) -> None:
    db_path = tmp_path / "retail.duckdb"
    build_database(db_path, SHORT_WINDOW_START, SHORT_WINDOW_DAYS)
    assert len(read_table(db_path, "dim_date")) == SHORT_WINDOW_DAYS
    assert len(read_table(db_path, "dim_store")) == 20
    assert 150 <= len(read_table(db_path, "dim_product")) <= 250


def test_rerun_overwrites_existing_database(tmp_path: Path) -> None:
    db_path = tmp_path / "retail.duckdb"
    build_database(db_path, SHORT_WINDOW_START, SHORT_WINDOW_DAYS)
    build_database(db_path, SHORT_WINDOW_START, SHORT_WINDOW_DAYS)  # must not fail or duplicate
    assert len(read_table(db_path, "dim_store")) == 20


def test_window_without_any_holiday_still_builds(tmp_path: Path) -> None:
    # 2025-03-03 is an ordinary Monday: the holiday table stays empty. This used to fail
    # while loading the empty frame.
    db_path = tmp_path / "one_day.duckdb"
    build_database(db_path, dt.date(2025, 3, 3), 1)
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        count = connection.execute("SELECT COUNT(*) FROM dim_holiday").fetchone()
    finally:
        connection.close()
    assert count == (0,)
