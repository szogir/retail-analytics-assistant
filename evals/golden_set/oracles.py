"""Independent case arithmetic; never imports or executes reference SQL."""

from collections.abc import Sequence

import polars as pl

from evals.reference_tools import ReferenceData, basket, grouped, number, total


def growth(new: object, base: object) -> float | None:
    """Return new / base - 1, or None when the base is missing or zero.

    Why: the SQL references divide by NULLIF(base, 0), which yields NULL. Python would
    raise ZeroDivisionError or KeyError, so the independent calculation needs the same
    explicit "no base" branch.
    """
    if new is None or base is None or not number(base):
        return None
    return number(new) / number(base) - 1


def _case_029(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 029 from base data, independently of SQL."""
    return [(total(d.window("2024-07-01", "2024-12-31").filter(pl.col("city") == "Budapest")),)]


def _case_030(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 030 from base data, independently of SQL."""
    f = d.window("2025-05-01", "2025-05-31", "AT")
    return [(float(number(f["net_eur"].sum())) / f["sales_date"].n_unique(),)]


def _case_031(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 031 from base data, independently of SQL."""
    return [
        (
            number(
                basket(
                    d.window("2025-01-01", "2025-03-31").filter(pl.col("store_name") == "Graz Nord")
                )
            ),
        )
    ]


def _case_032(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 032 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31", "HU")
    return [
        (
            f.filter(~pl.col("is_return") & (pl.col("sales_date").dt.weekday() >= 6))[
                "receipt_id"
            ].n_unique(),
        )
    ]


def _case_033(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 033 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31").filter(pl.col("category_en") == "Bakery")
    return [
        (
            number(f.filter(pl.col("is_private_label"))["net_eur"].sum())
            / number(f["net_eur"].sum()),
        )
    ]


def _case_034(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 034 from base data, independently of SQL."""
    f = d.window("2024-01-01", "2024-12-31", "HU")
    return [
        (
            -number(f.filter(pl.col("is_return"))["quantity"].sum())
            / number(f.filter(~pl.col("is_return"))["quantity"].sum()),
        )
    ]


def _case_035(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 035 from base data, independently of SQL."""
    f = d.window("2026-09-01", "2026-09-30")
    return [
        (
            int(
                number(
                    f.filter(
                        ~pl.col("is_return")
                        & pl.col("name_hu").str.contains("Teljes tej|Félzsíros tej")
                    )["quantity"].sum()
                )
            ),
        )
    ]


def _case_036(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 036 from base data, independently of SQL."""
    return [(total(d.window("2026-03-01", "2026-10-03")),)]


def _case_037(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 037 from base data, independently of SQL."""
    a = dict(grouped(d.window("2024-01-01", "2024-12-31"), ["country_code"]).iter_rows())
    b = dict(grouped(d.window("2025-01-01", "2025-12-31"), ["country_code"]).iter_rows())
    return [(k, growth(b.get(k), a[k])) for k in sorted(a)]


def _case_038(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 038 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31")
    values = [(c, number(basket(f.filter(pl.col("country_code") == c)))) for c in ("AT", "HU")]
    return sorted(values, key=lambda row: (-row[1], row[0]))[:1]


def _case_039(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 039 from base data, independently of SQL."""
    return [(total(d.window("2022-01-01", "2022-12-31")),)]


def _case_040(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 040 from base data, independently of SQL."""
    return [
        (
            d.window("2025-01-05", "2025-01-05", "AT")
            .filter(~pl.col("is_return"))["receipt_id"]
            .n_unique(),
        )
    ]


def _case_041(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 041 from base data, independently of SQL."""
    a = dict(grouped(d.window("2024-01-01", "2024-12-31"), ["store_id"]).iter_rows())
    b = dict(grouped(d.window("2025-01-01", "2025-12-31"), ["store_id"]).iter_rows())
    rows = [(k, growth(b.get(k), a[k])) for k in a]
    # Missing growth sorts last, like NULLS LAST in the reference SQL.
    return sorted(rows, key=lambda x: (x[1] is None, -(x[1] or 0.0), x[0]))[:3]


def _case_042(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 042 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31", "HU").with_columns(m=pl.col("sales_date").dt.month())
    v = dict(grouped(f, ["m"]).iter_rows())
    return [(m, growth(v.get(m), v.get(m - 1))) for m in range(2, 13)]


def _case_043(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 043 from base data, independently of SQL."""
    return [
        (i, total(d.window("2025-01-01", end)))
        for i, end in enumerate(["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"], 1)
    ]


def _case_044(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 044 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31").filter(~pl.col("is_return"))
    a = set(f.filter(pl.col("category_en") == "Dairy")["receipt_id"])
    b = set(f.filter(pl.col("category_en") == "Bakery")["receipt_id"])
    return [(len(a & b),)]


def _case_045(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 045 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31")
    return [
        (c, n / number(f["net_eur"].sum()) * 100)
        for c, n in grouped(f, ["country_code"]).iter_rows()
    ]


def _case_046(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 046 from base data, independently of SQL."""
    sold = set(d.window("2025-01-01", "2025-01-01").filter(~pl.col("is_return"))["product_id"])
    return [(len(set(d.tables["dim_product"]["product_id"]) - sold),)]


def _case_047(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 047 from base data, independently of SQL."""
    g = grouped(d.window("2025-01-01", "2025-12-31"), ["country_code", "category_en"])
    return (
        g.sort(["country_code", "net_eur", "category_en"], descending=[False, True, False])
        .unique(subset=["country_code"], keep="first", maintain_order=True)
        .rows()
    )


def expected(case_id: str, d: ReferenceData) -> list[tuple[object, ...]]:
    """Recompute the selected case using its independent arithmetic."""
    calculators = {
        "029": _case_029,
        "030": _case_030,
        "031": _case_031,
        "032": _case_032,
        "033": _case_033,
        "034": _case_034,
        "035": _case_035,
        "036": _case_036,
        "037": _case_037,
        "038": _case_038,
        "039": _case_039,
        "040": _case_040,
        "041": _case_041,
        "042": _case_042,
        "043": _case_043,
        "044": _case_044,
        "045": _case_045,
        "046": _case_046,
        "047": _case_047,
    }
    return list(calculators[case_id](d))
