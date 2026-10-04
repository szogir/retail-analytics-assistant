"""Independent DataFrame arithmetic for validating evaluation reference SQL.

Only base tables are exported from DuckDB; all filtering, joins and arithmetic
used by the second calculation happen in Polars, outside the reference SQL.
"""

import datetime as dt
from decimal import Decimal
from pathlib import Path

import duckdb
import polars as pl


def number(value: object) -> float:
    """Narrow a numeric DataFrame scalar, rejecting missing or nonnumeric values."""
    if not isinstance(value, int | float | Decimal) or isinstance(value, bool):
        raise ValueError(f"Expected a numeric scalar, got {type(value).__name__}")
    return float(value)


class ReferenceData:
    """Base tables and valid sales lines for independent reference checks."""

    def __init__(self, db_path: Path, folder: Path) -> None:
        """Load local tables through Parquet, preserving dates and numeric types."""
        folder.mkdir(parents=True, exist_ok=True)
        self.tables: dict[str, pl.DataFrame] = {}
        with duckdb.connect(str(db_path), read_only=True) as connection:
            for name in (
                "fact_sales",
                "dim_store",
                "dim_product",
                "dim_date",
                "fx_rate",
                "dim_holiday",
            ):
                target = str((folder / f"{name}.parquet").resolve()).replace("'", "''")
                connection.execute(f"COPY {name} TO '{target}' (FORMAT parquet)")  # noqa: S608
                self.tables[name] = pl.read_parquet(folder / f"{name}.parquet")
        self.all_lines = (
            self.tables["fact_sales"]
            .join(self.tables["dim_store"], on="store_id")
            .join(self.tables["dim_product"], on="product_id")
            .join(
                self.tables["fx_rate"].rename({"rate_date": "sales_date"}),
                on=["sales_date", "currency"],
            )
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
                vat_eur=pl.col("vat_amount") / pl.col("eur_rate"),
            )
        )
        self.valid = self.all_lines.filter(~pl.col("is_cancelled") & ~pl.col("is_test_store"))

    def window(self, first: str, last: str, country: str | None = None) -> pl.DataFrame:
        """Select an inclusive date interval and optionally one country."""
        frame = self.valid.filter(
            pl.col("sales_date").is_between(
                dt.date.fromisoformat(first), dt.date.fromisoformat(last)
            )
        )
        return frame if country is None else frame.filter(pl.col("country_code") == country)


def total(frame: pl.DataFrame, column: str = "net_eur") -> float | None:
    """Sum a measure, retaining SQL's NULL for an empty input."""
    return float(frame[column].sum()) if frame.height else None


def basket(frame: pl.DataFrame, column: str = "net_eur") -> float | None:
    """Average receipt totals, excluding returns, independently of SQL's ratio."""
    sales = frame.filter(~pl.col("is_return"))
    if not sales.height:
        return None
    receipts = sales.group_by("receipt_id").agg(pl.col(column).sum())
    return float(receipts[column].mean())  # type: ignore[arg-type]


def grouped(frame: pl.DataFrame, keys: list[str], column: str = "net_eur") -> pl.DataFrame:
    """Return sum per group with explicit grouping keys."""
    return frame.group_by(keys).agg(pl.col(column).sum())
