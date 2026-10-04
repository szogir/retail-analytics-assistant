"""Builds the whole synthetic database: dimensions, holidays, FX rates and sales.

What it does: calls the builders of `dimensions`, `closures` and `facts`, creates the
tables in a DuckDB file and bulk-loads them.

Why it exists: one place that defines the order of the steps and the table layout, so
that `data/retail.duckdb` is identical on every run (fixed seed, no clock, no locale).

Where it sits in the pipeline: before everything. The assistant, the golden set and the
evaluation read the file this script writes.

Run: `uv run python -m data_gen.generate`
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import tempfile
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

from data_gen.closures import build_dim_holiday, closed_holidays
from data_gen.dimensions import (
    DATA_DAYS,
    DATA_START,
    SEED,
    build_dim_date,
    build_dim_product,
    build_dim_store,
)
from data_gen.facts import build_fact_sales, build_fx_rates

DEFAULT_DB_PATH = Path("data") / "retail.duckdb"

DDL_STATEMENTS = [
    """CREATE TABLE dim_date (
        date DATE PRIMARY KEY,
        weekday VARCHAR NOT NULL,
        fiscal_week INTEGER NOT NULL,
        fiscal_month INTEGER NOT NULL,
        fiscal_year INTEGER NOT NULL
    )""",
    """CREATE TABLE dim_store (
        store_id INTEGER PRIMARY KEY,
        store_name VARCHAR NOT NULL,
        city VARCHAR NOT NULL,
        country_code VARCHAR NOT NULL,
        region_id INTEGER NOT NULL,
        region_name VARCHAR NOT NULL,
        is_test_store BOOLEAN NOT NULL
    )""",
    """CREATE TABLE dim_product (
        product_id INTEGER PRIMARY KEY,
        name_en VARCHAR NOT NULL,
        name_hu VARCHAR NOT NULL,
        category_en VARCHAR NOT NULL,
        category_hu VARCHAR NOT NULL,
        is_private_label BOOLEAN NOT NULL
    )""",
    # Public holidays on which the stores of that country are closed.
    """CREATE TABLE dim_holiday (
        country_code VARCHAR NOT NULL,
        holiday_date DATE NOT NULL,
        holiday_name VARCHAR NOT NULL,
        PRIMARY KEY (country_code, holiday_date)
    )""",
    # eur_rate = units of `currency` per 1 EUR (HUF about 370, EUR 1).
    # To convert an amount to euro, DIVIDE it by eur_rate.
    """CREATE TABLE fx_rate (
        rate_date DATE NOT NULL,
        currency VARCHAR NOT NULL,
        eur_rate DECIMAL(10, 2) NOT NULL,
        PRIMARY KEY (rate_date, currency)
    )""",
    # Design note: no FOREIGN KEY constraints. They slow down the bulk load and the data
    # tests check for orphan keys with queries instead.
    """CREATE TABLE fact_sales (
        receipt_id BIGINT NOT NULL,
        line_no INTEGER NOT NULL,
        sales_date DATE NOT NULL,
        store_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        gross_amount DECIMAL(14, 2) NOT NULL,
        discount_amount DECIMAL(14, 2) NOT NULL,
        vat_amount DECIMAL(14, 2) NOT NULL,
        currency VARCHAR NOT NULL,
        is_return BOOLEAN NOT NULL,
        is_cancelled BOOLEAN NOT NULL
    )""",
]

# Design note: column comments are real database metadata. They say what a column means
# (for example the direction of the exchange rate) without adding any business rule. The
# "naive" prompt mode ignores them; a "commented" mode prints them. Comparing naive ->
# commented -> semantic shows how much plain metadata helps and how much the semantic
# layer adds on top. Values are in single quotes, so no comment may contain one.
COLUMN_COMMENTS: dict[tuple[str, str], str] = {
    (
        "dim_date",
        "fiscal_year",
    ): "Fiscal year, named after the calendar year it starts in. It starts on 1 March.",
    ("dim_date", "fiscal_month"): "Fiscal month 1-12; March is 1.",
    (
        "dim_date",
        "fiscal_week",
    ): "Number of the 7-day block since the start of the fiscal year (1-53).",
    (
        "dim_store",
        "is_test_store",
    ): "TRUE for a store used for system tests. It is not a real store.",
    (
        "dim_product",
        "is_private_label",
    ): "TRUE for the own brand of the chain, FALSE for branded products.",
    (
        "dim_holiday",
        "holiday_date",
    ): "Public holiday of the country. Its stores are closed that day.",
    ("fx_rate", "eur_rate"): (
        "Units of the currency per 1 EUR (HUF is about 370, EUR is 1). "
        "To convert an amount to euro, DIVIDE it by this rate."
    ),
    ("fact_sales", "receipt_id"): "Receipt number. A receipt has several lines (line_no).",
    ("fact_sales", "quantity"): "Units sold. Negative on return lines.",
    (
        "fact_sales",
        "gross_amount",
    ): "Line amount including VAT, before discount, in the row currency. Negative on return lines.",
    ("fact_sales", "discount_amount"): "Promotion discount on the line, in the row currency.",
    (
        "fact_sales",
        "vat_amount",
    ): "VAT contained in the amount after discount, in the row currency.",
    ("fact_sales", "currency"): "Currency of the amounts in this row (HUF or EUR).",
    ("fact_sales", "is_return"): "TRUE if the receipt is a return of goods.",
    (
        "fact_sales",
        "is_cancelled",
    ): "TRUE on all lines of a cancelled receipt. A cancelled receipt is not a real sale.",
}

TABLE_NAMES = frozenset(
    {"dim_date", "dim_store", "dim_product", "dim_holiday", "fx_rate", "fact_sales"}
)


def load_frame(connection: duckdb.DuckDBPyConnection, table: str, frame: pl.DataFrame) -> None:
    """Bulk-load a polars DataFrame into an existing table.

    Why: the frame is written to a temporary Parquet file and read back by DuckDB in one
    `INSERT ... SELECT`. This loads 1.5 million rows in a fraction of a second.

    Design note: the alternatives were `executemany` (one statement per row, took 4
    seconds for only 600 dimension rows) and DuckDB's direct DataFrame reading, which
    needs the extra `pyarrow` package. A temporary file needs no new dependency.

    Args:
        connection: Open DuckDB connection.
        table: Target table name, must be one of the known tables.
        frame: Data to insert. Columns are matched to the table BY NAME.

    Raises:
        ValueError: If the table name is not one of the known tables.
        duckdb.Error: If the insert fails.
    """
    if table not in TABLE_NAMES:
        raise ValueError(f"unknown table: {table}")
    # Why: an empty frame has no columns, so the Parquet file would be unreadable
    # ("Need at least one non-root column"). The table already exists from the DDL, so
    # there is simply nothing to insert. This happens for `dim_holiday` when a short
    # date window contains no public holiday.
    if frame.is_empty():
        return
    with tempfile.TemporaryDirectory() as folder:
        parquet_path = Path(folder) / f"{table}.parquet"
        frame.write_parquet(parquet_path)
        # The table name was checked against the allow-list above.
        connection.execute(
            f"INSERT INTO {table} BY NAME SELECT * FROM read_parquet(?)",  # noqa: S608
            [parquet_path.as_posix()],
        )


def build_database(
    db_path: Path,
    start: dt.date = DATA_START,
    days: int = DATA_DAYS,
    seed: int = SEED,
) -> None:
    """Create the database file and fill every table.

    Why: an existing file is deleted first, so the result never depends on what an
    earlier run left behind (same seed -> same content, every time).

    Design note: each step has its own random stream, seeded from `[seed, n]`. Adding or
    changing one step then does not change the numbers of the others (for example the
    product prices stay the same when the sales logic changes).

    Args:
        db_path: Where to write the DuckDB file.
        start: First calendar day of the data.
        days: Number of consecutive days. Tests use a short window to stay fast.
        seed: Master seed.

    Raises:
        duckdb.Error: If a table cannot be created or filled.
    """
    product_rng = np.random.default_rng(seed)
    fx_rng = np.random.default_rng([seed, 1])
    sales_rng = np.random.default_rng([seed, 2])

    dates = build_dim_date(start, days)
    stores = build_dim_store()
    products = build_dim_product(product_rng)
    holidays = build_dim_holiday(dates[0].date, dates[-1].date)
    fx_rates = build_fx_rates(dates, fx_rng)
    sales = build_fact_sales(
        dates, stores, products, fx_rates, closed_holidays(holidays), sales_rng
    )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    connection = duckdb.connect(str(db_path))
    try:
        for statement in DDL_STATEMENTS:
            connection.execute(statement)
        for (table, column), comment in COLUMN_COMMENTS.items():
            connection.execute(f"COMMENT ON COLUMN {table}.{column} IS '{comment}'")  # noqa: S608
        load_frame(connection, "dim_date", pl.DataFrame(dates))
        load_frame(connection, "dim_store", pl.DataFrame(stores))
        # `base_price_eur` and `category_key` are generator-internal, not table columns.
        product_columns = [f.name for f in dataclasses.fields(products[0])]
        internal_columns = {"base_price_eur", "category_key"}
        load_frame(
            connection,
            "dim_product",
            pl.DataFrame(products).select(
                [c for c in product_columns if c not in internal_columns]
            ),
        )
        load_frame(connection, "dim_holiday", pl.DataFrame(holidays))
        load_frame(connection, "fx_rate", pl.DataFrame(fx_rates))
        load_frame(connection, "fact_sales", sales)
    finally:
        connection.close()


def main() -> None:
    """Generate the full database with the fixed seed."""
    build_database(DEFAULT_DB_PATH)
    print(f"Wrote {DEFAULT_DB_PATH}")


if __name__ == "__main__":
    main()
