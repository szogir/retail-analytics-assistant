"""Data tests for fx_rate and fact_sales (data_gen.facts) on the full database.

They check that the traps promised in the module docstring really are in the data, and
that the data is internally consistent (currencies, keys, closed days, amounts).
"""

import datetime as dt

import duckdb

from data_gen.dimensions import CATEGORIES, DATA_DAYS
from data_gen.generate import COLUMN_COMMENTS


def scalar(db: duckdb.DuckDBPyConnection, sql: str) -> float:
    row = db.execute(sql).fetchone()
    assert row is not None
    return float(row[0])


# --- fx_rate ------------------------------------------------------------------------


def test_fx_rate_has_one_row_per_day_and_currency(db: duckdb.DuckDBPyConnection) -> None:
    assert scalar(db, "SELECT COUNT(*) FROM fx_rate") == 2 * DATA_DAYS
    assert scalar(db, "SELECT COUNT(DISTINCT rate_date) FROM fx_rate") == DATA_DAYS


def test_huf_rate_moves_within_12_of_370(db: duckdb.DuckDBPyConnection) -> None:
    low = scalar(db, "SELECT MIN(eur_rate) FROM fx_rate WHERE currency = 'HUF'")
    high = scalar(db, "SELECT MAX(eur_rate) FROM fx_rate WHERE currency = 'HUF'")
    assert 358 <= low < high <= 382
    assert high - low > 10  # it really fluctuates, it is not a constant


def test_eur_rate_is_always_one(db: duckdb.DuckDBPyConnection) -> None:
    sql = "SELECT COUNT(*) FROM fx_rate WHERE currency = 'EUR' AND eur_rate <> 1"
    assert scalar(db, sql) == 0


def test_exchange_rate_direction_is_documented_in_the_column_comment(
    db: duckdb.DuckDBPyConnection,
) -> None:
    row = db.execute(
        "SELECT comment FROM duckdb_columns()"
        " WHERE table_name = 'fx_rate' AND column_name = 'eur_rate'"
    ).fetchone()
    assert row is not None
    assert "DIVIDE" in row[0]


def test_every_commented_column_exists(db: duckdb.DuckDBPyConnection) -> None:
    commented = db.execute(
        "SELECT COUNT(*) FROM duckdb_columns() WHERE comment IS NOT NULL"
    ).fetchone()
    assert commented == (len(COLUMN_COMMENTS),)


# --- fact_sales: size, keys, currencies ---------------------------------------------


def test_fact_sales_size_is_in_expected_range(db: duckdb.DuckDBPyConnection) -> None:
    assert 1_000_000 <= scalar(db, "SELECT COUNT(*) FROM fact_sales") <= 2_000_000


def test_no_orphan_foreign_keys(db: duckdb.DuckDBPyConnection) -> None:
    orphan_queries = [
        "SELECT COUNT(*) FROM fact_sales WHERE store_id NOT IN (SELECT store_id FROM dim_store)",
        "SELECT COUNT(*) FROM fact_sales"
        " WHERE product_id NOT IN (SELECT product_id FROM dim_product)",
        "SELECT COUNT(*) FROM fact_sales WHERE sales_date NOT IN (SELECT date FROM dim_date)",
        """SELECT COUNT(*) FROM fact_sales f
           LEFT JOIN fx_rate r ON r.rate_date = f.sales_date AND r.currency = f.currency
           WHERE r.rate_date IS NULL""",
    ]
    for sql in orphan_queries:
        assert scalar(db, sql) == 0


def test_currency_matches_store_country(db: duckdb.DuckDBPyConnection) -> None:
    sql = """
        SELECT COUNT(*) FROM fact_sales f JOIN dim_store s USING (store_id)
        WHERE (s.country_code = 'HU' AND f.currency <> 'HUF')
           OR (s.country_code = 'AT' AND f.currency <> 'EUR')
    """
    assert scalar(db, sql) == 0


# --- fact_sales: the built-in traps -------------------------------------------------


def test_cancelled_share_of_receipts_is_about_two_and_a_half_percent(
    db: duckdb.DuckDBPyConnection,
) -> None:
    sql = """
        SELECT COUNT(DISTINCT receipt_id) FILTER (WHERE is_cancelled)
             / COUNT(DISTINCT receipt_id) FROM fact_sales
    """
    assert 0.015 <= scalar(db, sql) <= 0.035


def test_a_receipt_is_cancelled_or_not_on_all_its_lines(db: duckdb.DuckDBPyConnection) -> None:
    sql = """
        SELECT COUNT(*) FROM (
            SELECT receipt_id FROM fact_sales
            GROUP BY receipt_id HAVING COUNT(DISTINCT is_cancelled) > 1
        )
    """
    assert scalar(db, sql) == 0


def test_test_store_has_sales(db: duckdb.DuckDBPyConnection) -> None:
    sql = """
        SELECT COUNT(*) FROM fact_sales f JOIN dim_store s USING (store_id)
        WHERE s.is_test_store
    """
    assert scalar(db, sql) > 0


def test_both_currencies_are_present_with_different_magnitudes(
    db: duckdb.DuckDBPyConnection,
) -> None:
    huf = scalar(db, "SELECT AVG(gross_amount) FROM fact_sales WHERE currency = 'HUF'")
    eur = scalar(db, "SELECT AVG(gross_amount) FROM fact_sales WHERE currency = 'EUR'")
    assert huf > 100 * eur  # summing them without conversion would be badly wrong


def test_returns_are_negative_and_sales_are_not(db: duckdb.DuckDBPyConnection) -> None:
    bad_returns = """
        SELECT COUNT(*) FROM fact_sales
        WHERE is_return AND (quantity >= 0 OR gross_amount >= 0 OR vat_amount > 0)
    """
    bad_sales = """
        SELECT COUNT(*) FROM fact_sales
        WHERE NOT is_return AND (quantity <= 0 OR gross_amount <= 0 OR discount_amount < 0)
    """
    assert scalar(db, bad_returns) == 0
    assert scalar(db, bad_sales) == 0
    share = scalar(db, "SELECT AVG(is_return::INT) FROM fact_sales")
    assert 0.005 <= share <= 0.03


def test_net_amount_is_positive_and_vat_is_inside_the_gross(
    db: duckdb.DuckDBPyConnection,
) -> None:
    sql = """
        SELECT COUNT(*) FROM fact_sales
        WHERE NOT is_return AND gross_amount - discount_amount - vat_amount <= 0
    """
    assert scalar(db, sql) == 0


def test_vat_matches_country_and_category_rate(db: duckdb.DuckDBPyConnection) -> None:
    rates = {c.name_en: (c.vat_hu_percent, c.vat_at_percent) for c in CATEGORIES}
    rows = db.execute(
        """
        SELECT p.category_en, s.country_code, f.gross_amount, f.discount_amount, f.vat_amount
        FROM fact_sales f
        JOIN dim_product p USING (product_id)
        JOIN dim_store s USING (store_id)
        USING SAMPLE reservoir(3000 ROWS) REPEATABLE (42)
        """
    ).fetchall()
    for category, country, gross, discount, vat in rows:
        hu_rate, at_rate = rates[category]
        rate = hu_rate if country == "HU" else at_rate
        expected = float(gross - discount) * rate / (100 + rate)
        tolerance = 0.51 if country == "HU" else 0.011  # rounding to whole HUF / cents
        assert abs(float(vat) - expected) <= tolerance


# --- fact_sales: closed days and patterns -------------------------------------------


def test_no_sales_on_holidays_in_that_country(db: duckdb.DuckDBPyConnection) -> None:
    sql = """
        SELECT COUNT(*) FROM fact_sales f
        JOIN dim_store s USING (store_id)
        JOIN dim_holiday h ON h.country_code = s.country_code AND h.holiday_date = f.sales_date
    """
    assert scalar(db, sql) == 0


def test_no_austrian_sales_on_sundays_but_hungarian_sunday_sales_exist(
    db: duckdb.DuckDBPyConnection,
) -> None:
    sunday_sales = """
        SELECT COUNT(*) FROM fact_sales f JOIN dim_store s USING (store_id)
        WHERE s.country_code = '{country}' AND dayofweek(f.sales_date) = 0
    """
    assert scalar(db, sunday_sales.format(country="AT")) == 0
    assert scalar(db, sunday_sales.format(country="HU")) > 0


def test_christmas_has_no_sales_but_the_days_around_it_have(
    db: duckdb.DuckDBPyConnection,
) -> None:
    on_holiday = db.execute(
        "SELECT COUNT(*) FROM fact_sales WHERE sales_date = ?", [dt.date(2024, 12, 25)]
    ).fetchone()
    before = db.execute(
        "SELECT COUNT(*) FROM fact_sales WHERE sales_date = ?", [dt.date(2024, 12, 23)]
    ).fetchone()
    assert on_holiday == (0,)
    assert before is not None
    assert before[0] > 0


def test_volume_grows_year_over_year(db: duckdb.DuckDBPyConnection) -> None:
    sql = """
        SELECT d.fiscal_year, COUNT(*) FROM fact_sales f JOIN dim_date d ON d.date = f.sales_date
        WHERE d.fiscal_year IN (2023, 2024, 2025) GROUP BY 1 ORDER BY 1
    """
    counts = [row[1] for row in db.execute(sql).fetchall()]
    assert counts == sorted(counts)
    assert counts[0] < counts[-1]


def test_saturday_is_the_peak_day_in_hungary(db: duckdb.DuckDBPyConnection) -> None:
    sql = """
        SELECT dayofweek(sales_date) AS weekday, COUNT(*) / COUNT(DISTINCT sales_date) AS per_day
        FROM fact_sales f JOIN dim_store s USING (store_id)
        WHERE s.country_code = 'HU' GROUP BY 1 ORDER BY per_day DESC LIMIT 1
    """
    row = db.execute(sql).fetchone()
    assert row is not None
    assert row[0] == 6  # DuckDB: Sunday = 0 ... Saturday = 6


def test_december_is_busier_than_an_average_month(db: duckdb.DuckDBPyConnection) -> None:
    sql = """
        SELECT month(sales_date) AS m, COUNT(*) AS n FROM fact_sales
        WHERE year(sales_date) = 2024 GROUP BY 1
    """
    counts = dict(db.execute(sql).fetchall())
    average = sum(counts.values()) / len(counts)
    assert counts[12] > 1.2 * average
