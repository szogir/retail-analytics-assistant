"""Independent check of the golden-set reference answers.

Why it exists: the reference SQL defines the "correct" answer of every eval case. If it
is wrong, the eval would grade a good model answer as wrong and nothing would warn us.
`test_golden_set.py` only proves that the SQL runs. Here every answer is recomputed a
second time WITHOUT SQL joins: the tables are read into polars frames and the business
rules are applied step by step in Python. The two results must agree.

Where it sits in the pipeline: tests only (evaluation layer).
"""

import datetime as dt
from decimal import Decimal
from pathlib import Path

import duckdb
import polars as pl
import pytest

from evals.golden import load_golden_set

CASES = {case.id: case for case in load_golden_set()}
REL = 1e-9  # both sides sum the same floats, only in a different order


@pytest.fixture(scope="module")
def tables(full_db_path: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, pl.DataFrame]:
    """Read the tables into polars frames (through Parquet, no extra dependency)."""
    folder = tmp_path_factory.mktemp("frames")
    connection = duckdb.connect(str(full_db_path), read_only=True)
    try:
        frames: dict[str, pl.DataFrame] = {}
        for name in ("fact_sales", "dim_store", "dim_product", "dim_date", "fx_rate"):
            path = (folder / f"{name}.parquet").as_posix()
            connection.execute(f"COPY {name} TO '{path}' (FORMAT parquet)")  # noqa: S608
            frames[name] = pl.read_parquet(path)
    finally:
        connection.close()
    return frames


@pytest.fixture(scope="module")
def lines(tables: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Valid sales lines (not cancelled, not a test store) with euro net sales."""
    stores = tables["dim_store"].select("store_id", "store_name", "country_code", "is_test_store")
    fx = tables["fx_rate"].rename({"rate_date": "sales_date"})
    products = tables["dim_product"].select("product_id", "category_en", "is_private_label")
    dates = tables["dim_date"].select(
        pl.col("date").alias("sales_date"), "weekday", "fiscal_month", "fiscal_year"
    )
    return (
        tables["fact_sales"]
        .filter(~pl.col("is_cancelled"))
        .join(stores, on="store_id")
        .filter(~pl.col("is_test_store"))
        .join(fx, on=["sales_date", "currency"])
        .join(products, on="product_id")
        .join(dates, on="sales_date")
        # DuckDB returns DECIMAL columns; plain floats keep the arithmetic simple.
        .with_columns(
            pl.col("gross_amount", "discount_amount", "vat_amount", "eur_rate").cast(pl.Float64)
        )
        .with_columns(
            net_local=pl.col("gross_amount") - pl.col("discount_amount") - pl.col("vat_amount")
        )
        .with_columns(
            net_eur=pl.col("net_local") / pl.col("eur_rate"),
            gross_eur=pl.col("gross_amount") / pl.col("eur_rate"),
            discount_eur=pl.col("discount_amount") / pl.col("eur_rate"),
        )
    )


def reference(db: duckdb.DuckDBPyConnection, case_id: str) -> list[tuple[object, ...]]:
    """Run the reference SQL of a case."""
    sql = CASES[case_id].reference_sql
    assert sql is not None
    rows = db.execute(sql).fetchall()
    return [tuple(float(v) if isinstance(v, Decimal) else v for v in row) for row in rows]


def between(frame: pl.DataFrame, first: dt.date, last: dt.date) -> pl.DataFrame:
    """Rows with first <= sales_date <= last."""
    return frame.filter((pl.col("sales_date") >= first) & (pl.col("sales_date") <= last))


def calendar_2025(frame: pl.DataFrame) -> pl.DataFrame:
    return between(frame, dt.date(2025, 1, 1), dt.date(2025, 12, 31))


def test_001_net_sales_by_country_fiscal_2025(
    lines: pl.DataFrame, db: duckdb.DuckDBPyConnection
) -> None:
    # Fiscal year 2025 by explicit dates instead of the dim_date column.
    window = between(lines, dt.date(2025, 3, 1), dt.date(2026, 2, 28))
    expected = dict(window.group_by("country_code").agg(pl.col("net_eur").sum()).iter_rows())
    actual = {str(country): float(value) for country, value in reference(db, "001")}  # type: ignore[arg-type]
    assert actual.keys() == expected.keys() == {"AT", "HU"}
    for country, value in expected.items():
        assert actual[country] == pytest.approx(value, rel=REL)


def test_002_net_sales_september_2026(lines: pl.DataFrame, db: duckdb.DuckDBPyConnection) -> None:
    window = between(lines, dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    assert reference(db, "002")[0][0] == pytest.approx(window["net_eur"].sum(), rel=REL)


def test_003_receipt_count_hungary_2025(lines: pl.DataFrame, db: duckdb.DuckDBPyConnection) -> None:
    window = calendar_2025(lines).filter((pl.col("country_code") == "HU") & ~pl.col("is_return"))
    assert reference(db, "003")[0][0] == window["receipt_id"].n_unique()


def test_004_average_basket_2025(lines: pl.DataFrame, db: duckdb.DuckDBPyConnection) -> None:
    sales = calendar_2025(lines).filter(~pl.col("is_return"))
    # Built from per-receipt totals: mean of receipt totals = sum / number of receipts.
    expected: dict[str, float] = {}
    for country in ("AT", "HU"):
        receipts = (
            sales.filter(pl.col("country_code") == country)
            .group_by("receipt_id")
            .agg(pl.col("net_eur").sum())
        )
        expected[country] = float(receipts["net_eur"].mean())  # type: ignore[arg-type]
    actual = {str(country): float(value) for country, value in reference(db, "004")}  # type: ignore[arg-type]
    for country, value in expected.items():
        assert actual[country] == pytest.approx(value, rel=REL)


def test_004_returns_in_or_out_changes_the_basket(
    lines: pl.DataFrame, db: duckdb.DuckDBPyConnection
) -> None:
    # Documents the size of the "returns in or out" ambiguity: if it were zero, the
    # convention written in the case notes would be pointless.
    window = calendar_2025(lines).filter(pl.col("country_code") == "HU")
    with_returns = window["net_eur"].sum() / window["receipt_id"].n_unique()
    actual = {str(country): float(value) for country, value in reference(db, "004")}  # type: ignore[arg-type]
    assert actual["HU"] != pytest.approx(with_returns, rel=1e-4)


def test_005_fiscal_month_3_is_may_2025(lines: pl.DataFrame, db: duckdb.DuckDBPyConnection) -> None:
    window = between(lines, dt.date(2025, 5, 1), dt.date(2025, 5, 31))
    assert reference(db, "005")[0][0] == pytest.approx(window["net_eur"].sum(), rel=REL)


def test_006_best_weekday_2025(lines: pl.DataFrame, db: duckdb.DuckDBPyConnection) -> None:
    totals = calendar_2025(lines).group_by("weekday").agg(pl.col("net_eur").sum())
    best = totals.sort("net_eur", descending=True)["weekday"][0]
    assert reference(db, "006") == [(best,)]


def test_007_private_label_share_fiscal_2025(
    lines: pl.DataFrame, db: duckdb.DuckDBPyConnection
) -> None:
    window = between(lines, dt.date(2025, 3, 1), dt.date(2026, 2, 28))
    share = window.filter(pl.col("is_private_label"))["net_eur"].sum() / window["net_eur"].sum()
    assert reference(db, "007")[0][0] == pytest.approx(share, rel=REL)
    assert 0 < share < 1


def test_008_return_rate_fiscal_2025(lines: pl.DataFrame, db: duckdb.DuckDBPyConnection) -> None:
    window = between(lines, dt.date(2025, 3, 1), dt.date(2026, 2, 28))
    returned = -window.filter(pl.col("is_return"))["quantity"].sum()
    sold = window.filter(~pl.col("is_return"))["quantity"].sum()
    assert reference(db, "008")[0][0] == pytest.approx(returned / sold, rel=REL)
    assert 0 < returned / sold < 0.2  # a fraction, not a percentage


def test_009_top_categories_2025(lines: pl.DataFrame, db: duckdb.DuckDBPyConnection) -> None:
    totals = (
        calendar_2025(lines)
        .group_by("category_en")
        .agg(pl.col("net_eur").sum())
        .sort("net_eur", descending=True)
        .head(5)
    )
    actual = reference(db, "009")
    assert [row[0] for row in actual] == totals["category_en"].to_list()
    for row, expected in zip(actual, totals["net_eur"].to_list(), strict=True):
        assert row[1] == pytest.approx(expected, rel=REL)


def test_010_daily_average_austria_2025(lines: pl.DataFrame, db: duckdb.DuckDBPyConnection) -> None:
    window = calendar_2025(lines).filter(pl.col("country_code") == "AT")
    trading_days = window["sales_date"].n_unique()
    expected = window["net_local"].sum() / trading_days
    assert reference(db, "010")[0][0] == pytest.approx(expected, rel=REL)
    # Closed on Sundays and public holidays: clearly fewer than 365 trading days.
    assert 250 < trading_days < 320


def test_011_hungary_had_13_holidays_in_2025(db: duckdb.DuckDBPyConnection) -> None:
    # The generator has 13 Hungarian holiday rules and all of them fall into 2025.
    assert reference(db, "011") == [(13,)]


def test_012_cancelled_share_2025(
    tables: dict[str, pl.DataFrame], db: duckdb.DuckDBPyConnection
) -> None:
    # Here the cancelled receipts are the subject, so the "valid lines" frame is not used.
    test_stores = tables["dim_store"].filter(pl.col("is_test_store"))["store_id"].to_list()
    sales = calendar_2025(
        tables["fact_sales"].filter(~pl.col("store_id").is_in(test_stores) & ~pl.col("is_return"))
    )
    per_receipt = sales.group_by("receipt_id").agg(pl.col("is_cancelled").any())
    share = per_receipt["is_cancelled"].sum() / per_receipt.height
    assert reference(db, "012")[0][0] == pytest.approx(share, rel=REL)
    assert 0.005 < share < 0.1  # the generator builds in a few percent of cancellations


def test_013_store_counts_without_the_test_store(
    tables: dict[str, pl.DataFrame], db: duckdb.DuckDBPyConnection
) -> None:
    stores = tables["dim_store"]
    expected = {
        country: stores.filter(
            (pl.col("country_code") == country) & ~pl.col("is_test_store")
        ).height
        for country in ("AT", "HU")
    }
    assert dict(reference(db, "013")) == expected  # type: ignore[arg-type]
    # The trap: with the test store, Hungary would have one store more.
    assert stores.filter(pl.col("country_code") == "HU").height == expected["HU"] + 1


def test_014_gross_sales_hungary_september_2026(
    lines: pl.DataFrame, db: duckdb.DuckDBPyConnection
) -> None:
    window = between(lines, dt.date(2026, 9, 1), dt.date(2026, 9, 30)).filter(
        pl.col("country_code") == "HU"
    )
    assert reference(db, "014")[0][0] == pytest.approx(window["gross_eur"].sum(), rel=REL)


def test_015_discount_rate_2025(lines: pl.DataFrame, db: duckdb.DuckDBPyConnection) -> None:
    window = calendar_2025(lines)
    expected = window["discount_eur"].sum() / window["gross_eur"].sum()
    assert reference(db, "015")[0][0] == pytest.approx(expected, rel=REL)
    assert 0 < expected < 0.5  # a fraction, not a percentage


def test_016_units_sold_fiscal_2025(lines: pl.DataFrame, db: duckdb.DuckDBPyConnection) -> None:
    window = between(lines, dt.date(2025, 3, 1), dt.date(2026, 2, 28)).filter(~pl.col("is_return"))
    assert reference(db, "016")[0][0] == window["quantity"].sum()


def test_017_top_3_stores_2025(lines: pl.DataFrame, db: duckdb.DuckDBPyConnection) -> None:
    totals = (
        calendar_2025(lines)
        .group_by("store_name")
        .agg(pl.col("net_eur").sum())
        .sort("net_eur", descending=True)
        .head(3)
    )
    actual = reference(db, "017")
    assert [row[0] for row in actual] == totals["store_name"].to_list()
    for row, expected in zip(actual, totals["net_eur"].to_list(), strict=True):
        assert row[1] == pytest.approx(expected, rel=REL)


def test_018_year_to_date_2026(lines: pl.DataFrame, db: duckdb.DuckDBPyConnection) -> None:
    window = between(lines, dt.date(2026, 1, 1), dt.date(2026, 10, 3))
    assert reference(db, "018")[0][0] == pytest.approx(window["net_eur"].sum(), rel=REL)


def test_019_december_is_the_best_month_2025(
    lines: pl.DataFrame, db: duckdb.DuckDBPyConnection
) -> None:
    months = (
        calendar_2025(lines)
        .with_columns(month=pl.col("sales_date").dt.month())
        .group_by("month")
        .agg(pl.col("net_eur").sum())
        .sort("net_eur", descending=True)
    )
    assert reference(db, "019") == [(months["month"][0],)] == [(12,)]


def test_020_average_basket_huf_december_2025(
    lines: pl.DataFrame, db: duckdb.DuckDBPyConnection
) -> None:
    window = between(lines, dt.date(2025, 12, 1), dt.date(2025, 12, 31)).filter(
        (pl.col("country_code") == "HU") & ~pl.col("is_return")
    )
    receipts = window.group_by("receipt_id").agg(pl.col("net_local").sum())
    expected = float(receipts["net_local"].mean())  # type: ignore[arg-type]
    assert reference(db, "020")[0][0] == pytest.approx(expected, rel=REL)


def test_021_average_net_sales_per_store_2025(
    lines: pl.DataFrame, db: duckdb.DuckDBPyConnection
) -> None:
    per_store = calendar_2025(lines).group_by("store_id").agg(pl.col("net_eur").sum())
    assert per_store.height == 19  # the test store is already filtered out of `lines`
    expected = float(per_store["net_eur"].mean())  # type: ignore[arg-type]
    assert reference(db, "021")[0][0] == pytest.approx(expected, rel=REL)


def test_fiscal_calendar_matches_the_case_notes(tables: dict[str, pl.DataFrame]) -> None:
    fiscal_2025 = tables["dim_date"].filter(pl.col("fiscal_year") == 2025)
    assert (fiscal_2025["date"].min(), fiscal_2025["date"].max()) == (
        dt.date(2025, 3, 1),
        dt.date(2026, 2, 28),
    )
    month_3 = fiscal_2025.filter(pl.col("fiscal_month") == 3)
    assert (month_3["date"].min(), month_3["date"].max()) == (
        dt.date(2025, 5, 1),
        dt.date(2025, 5, 31),
    )


def test_country_totals_add_up_to_the_grand_total(
    lines: pl.DataFrame, db: duckdb.DuckDBPyConnection
) -> None:
    # Cross-check between cases: the per-country split of case 001 must add up to the
    # total of the same window computed without any grouping.
    split = sum(float(row[1]) for row in reference(db, "001"))  # type: ignore[arg-type]
    window = between(lines, dt.date(2025, 3, 1), dt.date(2026, 2, 28))
    assert split == pytest.approx(window["net_eur"].sum(), rel=REL)
