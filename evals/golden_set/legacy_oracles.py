"""Independent arithmetic for the original 21 development result cases.

These computations mirror the established Polars reference tests while exposing
a callable interface for the suite release gate and the human review report.
"""

import polars as pl

from evals.reference_tools import ReferenceData, basket, grouped, number, total


def expected(case_id: str, d: ReferenceData) -> list[tuple[object, ...]]:
    """Recompute an original reference using base tables and DataFrame operations."""
    calendar = d.window("2025-01-01", "2025-12-31")
    fiscal = d.window("2025-03-01", "2026-02-28")
    if case_id == "001":
        return grouped(fiscal, ["country_code"]).sort("country_code").rows()
    if case_id == "002":
        return [(total(d.window("2026-09-01", "2026-09-30")),)]
    if case_id == "003":
        return [
            (
                calendar.filter((pl.col("country_code") == "HU") & ~pl.col("is_return"))[
                    "receipt_id"
                ].n_unique(),
            )
        ]
    if case_id == "004":
        return [(c, basket(calendar.filter(pl.col("country_code") == c))) for c in ["AT", "HU"]]
    if case_id == "005":
        return [(total(d.window("2025-05-01", "2025-05-31")),)]
    if case_id == "006":
        days = calendar.with_columns(weekday=pl.col("sales_date").dt.strftime("%A"))
        best = grouped(days, ["weekday"]).sort("net_eur", descending=True)["weekday"][0]
        return [(best,)]
    if case_id == "007":
        return [
            (
                number(fiscal.filter(pl.col("is_private_label"))["net_eur"].sum())
                / number(fiscal["net_eur"].sum()),
            )
        ]
    if case_id == "008":
        return [
            (
                -number(fiscal.filter(pl.col("is_return"))["quantity"].sum())
                / number(fiscal.filter(~pl.col("is_return"))["quantity"].sum()),
            )
        ]
    if case_id == "009":
        return grouped(calendar, ["category_en"]).sort("net_eur", descending=True).head(5).rows()
    if case_id == "010":
        austria = calendar.filter(pl.col("country_code") == "AT")
        return [(number(austria["net_local"].sum()) / austria["sales_date"].n_unique(),)]
    if case_id == "011":
        return [
            (
                d.tables["dim_holiday"]
                .filter(
                    (pl.col("country_code") == "HU") & (pl.col("holiday_date").dt.year() == 2025)
                )
                .height,
            )
        ]
    if case_id == "012":
        eligible = d.all_lines.filter(
            ~pl.col("is_test_store")
            & ~pl.col("is_return")
            & (pl.col("sales_date").dt.year() == 2025)
        )
        receipts = eligible.group_by("receipt_id").agg(pl.col("is_cancelled").any())
        return [(number(receipts["is_cancelled"].sum()) / receipts.height,)]
    if case_id == "013":
        return (
            d.tables["dim_store"]
            .filter(~pl.col("is_test_store"))
            .group_by("country_code")
            .len()
            .sort("country_code")
            .rows()
        )
    if case_id == "014":
        return [(total(d.window("2026-09-01", "2026-09-30", "HU"), "gross_eur"),)]
    if case_id == "015":
        return [(number(calendar["discount_eur"].sum()) / number(calendar["gross_eur"].sum()),)]
    if case_id == "016":
        return [(number(fiscal.filter(~pl.col("is_return"))["quantity"].sum()),)]
    if case_id == "017":
        return grouped(calendar, ["store_name"]).sort("net_eur", descending=True).head(3).rows()
    if case_id == "018":
        return [(total(d.window("2026-01-01", "2026-10-03")),)]
    if case_id == "019":
        months = calendar.with_columns(m=pl.col("sales_date").dt.month())
        return [(grouped(months, ["m"]).sort("net_eur", descending=True)["m"][0],)]
    if case_id == "020":
        return [(basket(d.window("2025-12-01", "2025-12-31", "HU"), "net_local"),)]
    if case_id == "021":
        return [(number(grouped(calendar, ["store_id"])["net_eur"].mean()),)]
    raise ValueError(f"No legacy reference for {case_id}")
