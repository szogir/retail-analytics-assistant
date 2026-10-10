"""Independent case arithmetic; never imports or executes reference SQL."""

import datetime as dt
from collections.abc import Sequence

import polars as pl

from evals.reference_tools import ReferenceData, basket, grouped, number, total


def _case_101(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 101 from base data, independently of SQL."""
    f = d.window("2024-01-01", "2024-12-31", "HU")
    return [(k, v / number(f["net_eur"].sum())) for k, v in grouped(f, ["region_name"]).iter_rows()]


def _case_102(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 102 from base data, independently of SQL."""
    f = d.window("2024-01-01", "2024-12-31", "AT")
    v = [(m, number(basket(f.filter(pl.col("sales_date").dt.month() == m)))) for m in range(1, 13)]
    return sorted(v, key=lambda x: (x[1], x[0]))[:1]


def _case_103(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 103 from base data, independently of SQL."""
    hu = d.window("2025-01-01", "2025-12-31", "HU")
    at = d.window("2025-01-01", "2025-12-31", "AT")
    return [
        (
            number(hu["net_eur"].sum()) / hu["sales_date"].n_unique()
            - number(at["net_eur"].sum()) / at["sales_date"].n_unique(),
        )
    ]


def _case_104(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 104 from base data, independently of SQL."""
    f = d.window("2024-03-01", "2025-02-28").filter(pl.col("is_return"))
    return [(c, -n) for c, n in grouped(f, ["country_code"]).iter_rows()]


def _case_105(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 105 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31", "HU")
    v = []
    for c in f["category_en"].unique():
        g = f.filter(pl.col("category_en") == c)
        v.append(
            (
                c,
                number(g.filter(pl.col("is_private_label"))["net_eur"].sum())
                / number(g["net_eur"].sum()),
            )
        )
    return sorted(v, key=lambda x: (-x[1], x[0]))[:1]


def _case_106(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 106 from base data, independently of SQL."""
    f = d.window("2024-03-01", "2025-02-28", "HU").filter(~pl.col("is_return"))
    return [
        (i, f.filter(pl.col("sales_date").dt.month() == m)["receipt_id"].n_unique())
        for i, m in enumerate([3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2], 1)
    ]


def _case_107(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 107 from base data, independently of SQL."""
    f = d.window("2025-09-22", "2025-09-28", "HU").filter(~pl.col("is_return"))
    return (
        grouped(f, ["product_id"], "quantity")
        .sort(["quantity", "product_id"], descending=[True, False])
        .head(3)
        .rows()
    )


def _case_108(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 108 from base data, independently of SQL."""
    f = d.window("2024-01-01", "2024-12-31", "HU")
    return [
        (
            number(f.filter(pl.col("sales_date").dt.weekday() >= 6)["net_eur"].sum())
            / number(f["net_eur"].sum()),
        )
    ]


def _case_109(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 109 from base data, independently of SQL."""
    a = dict(grouped(d.window("2025-03-01", "2025-10-03"), ["country_code"]).iter_rows())
    b = dict(grouped(d.window("2026-03-01", "2026-10-03"), ["country_code"]).iter_rows())
    return [(c, b[c] / a[c] - 1) for c in sorted(a)]


def _case_110(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 110 from base data, independently of SQL."""
    a = d.window("2024-01-01", "2024-12-31")
    b = d.window("2025-01-01", "2025-12-31")
    v = [
        (
            c,
            number(basket(b.filter(pl.col("city") == c)))
            - number(basket(a.filter(pl.col("city") == c))),
        )
        for c in a["city"].unique()
    ]
    return sorted(v, key=lambda x: (-x[1], x[0]))[:1]


def _case_111(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 111 from base data, independently of SQL."""
    return [(total(d.window("2025-01-01", "2025-12-31", "DE")),)]


def _case_112(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 112 from base data, independently of SQL."""
    return grouped(d.window("2023-02-20", "2023-02-28"), ["sales_date"]).sort("sales_date").rows()


def _case_113(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 113 from base data, independently of SQL."""
    return [
        (
            d.window("2025-12-25", "2025-12-25", "AT")
            .filter(~pl.col("is_return"))["receipt_id"]
            .n_unique(),
        )
    ]


def _case_114(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 114 from base data, independently of SQL."""
    return [(basket(d.window("2025-12-25", "2025-12-25", "AT")),)]


def _case_115(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 115 from base data, independently of SQL."""
    a = dict(grouped(d.window("2024-03-01", "2025-02-28"), ["category_en"]).iter_rows())
    b = dict(grouped(d.window("2025-03-01", "2026-02-28"), ["category_en"]).iter_rows())
    return sorted([(c, b[c] - a[c]) for c in a], key=lambda x: (-x[1], x[0]))[:1]


def _case_116(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 116 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31")
    return [
        (
            c,
            *[
                total(f.filter(pl.col("country_code") == c), m)
                for m in ["gross_eur", "discount_eur", "vat_eur", "net_eur"]
            ],
        )
        for c in ["AT", "HU"]
    ]


def _case_117(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 117 from base data, independently of SQL."""
    g = grouped(d.window("2025-01-01", "2025-12-31"), ["country_code", "region_name"])
    return (
        g.sort(["country_code", "net_eur", "region_name"], descending=[False, True, False])
        .group_by("country_code", maintain_order=True)
        .head(2)
        .rows()
    )


def _case_118(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 118 from base data, independently of SQL."""
    a = dict(
        grouped(
            d.window("2024-01-01", "2024-12-31").filter(~pl.col("is_return")),
            ["category_en"],
            "quantity",
        ).iter_rows()
    )
    b = dict(
        grouped(
            d.window("2025-01-01", "2025-12-31").filter(~pl.col("is_return")),
            ["category_en"],
            "quantity",
        ).iter_rows()
    )
    return [(c, b[c] / a[c] - 1) for c in a]


def _case_119(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 119 from base data, independently of SQL."""
    g = grouped(d.window("2025-01-01", "2025-12-31", "HU"), ["sales_date"])
    return [(g.filter(pl.col("net_eur") > number(g["net_eur"].mean())).height,)]


def _case_120(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 120 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31", "AT").with_columns(m=pl.col("sales_date").dt.month())
    v = dict(grouped(f, ["m"]).iter_rows())
    return sorted(
        [(m, v[m] - v[m - 1]) for m in range(2, 13) if v[m] < v[m - 1]], key=lambda x: (x[1], x[0])
    )[:1]


def _case_121(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 121 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31", "HU").filter(~pl.col("is_return"))
    return [
        (
            f.group_by("receipt_id")
            .agg(pl.col("product_id").n_unique())
            .filter(pl.col("product_id") >= 3)
            .height,
        )
    ]


def _case_122(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 122 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31", "AT").filter(~pl.col("is_return"))
    return [
        (
            f.filter(pl.col("is_private_label"))["receipt_id"].n_unique()
            / f["receipt_id"].n_unique(),
        )
    ]


def _case_123(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 123 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31", "HU").filter(~pl.col("is_return"))
    g = f.group_by("receipt_id").agg(pl.col("is_private_label").all())
    return [(100 * g.filter(pl.col("is_private_label")).height / g.height,)]


def _case_124(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 124 from base data, independently of SQL."""
    f = (
        d.window("2025-01-01", "2025-12-31", "AT")
        .filter(~pl.col("is_return"))
        .with_columns(m=pl.col("sales_date").dt.month())
    )
    return [
        (f.group_by("product_id").agg(pl.col("m").n_unique()).filter(pl.col("m") == 12).height,)
    ]


def _case_125(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 125 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31").filter(~pl.col("is_return"))
    a = set(f.filter(pl.col("country_code") == "AT")["sales_date"])
    b = set(f.filter(pl.col("country_code") == "HU")["sales_date"])
    return [(len(a & b),)]


def _case_126(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 126 from base data, independently of SQL."""
    f = d.window("2025-06-01", "2025-06-01").filter(~pl.col("is_return"))
    return [(c, f.filter(pl.col("country_code") == c)["store_id"].n_unique()) for c in ["AT", "HU"]]


def _case_127(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 127 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31").filter(
        pl.col("name_hu").str.contains("Teljes tej|Félzsíros tej")
    )
    v = []
    for c in ["AT", "HU"]:
        g = f.filter(pl.col("country_code") == c)
        v.append(
            (
                c,
                number(g.filter(pl.col("is_private_label"))["net_eur"].sum())
                / number(g["net_eur"].sum()),
            )
        )
    return v


def _case_128(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 128 from base data, independently of SQL."""
    f = (
        d.window("2025-01-01", "2025-12-31", "AT")
        .filter(~pl.col("is_return"))
        .with_columns(w=pl.col("sales_date").dt.weekday())
    )
    return [(w, number(basket(f.filter(pl.col("w") == w)))) for w in sorted(f["w"].unique())]


def _case_130(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 130 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31").filter(pl.col("is_return"))
    v = [(p, -q) for p, q in grouped(f, ["product_id"], "quantity").iter_rows()]
    return sorted(v, key=lambda x: (-x[1], x[0]))[:1]


def _case_131(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 131 from base data, independently of SQL."""
    g = grouped(d.window("2025-01-01", "2025-12-31"), ["store_id", "sales_date"])
    return [(g.filter(pl.col("net_eur") < 0).height,)]


def _case_132(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 132 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31", "HU").filter(~pl.col("is_return"))
    v = []
    for r in f["region_name"].unique():
        g = f.filter(pl.col("region_name") == r)
        v.append((r, g["receipt_id"].n_unique() / g["sales_date"].n_unique()))
    return v


def _case_133(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute labelled calendar and fiscal quarter totals independently of SQL."""
    return [
        ("calendar_q1", total(d.window("2025-01-01", "2025-03-31"))),
        ("fiscal_q1", total(d.window("2025-03-01", "2025-05-31"))),
    ]


def _case_134(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 134 from base data, independently of SQL."""
    return [(total(d.window("2024-02-28", "2024-02-29")),)]


def _case_135(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 135 from base data, independently of SQL."""
    a = dict(grouped(d.window("2026-08-01", "2026-08-31"), ["country_code"]).iter_rows())
    b = dict(grouped(d.window("2026-09-01", "2026-09-30"), ["country_code"]).iter_rows())
    return [(c, b[c] / a[c] - 1) for c in a]


def _case_136(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Average each non-return receipt's largest net euro line independently of SQL."""
    sales = d.window("2025-01-01", "2025-12-31", "HU").filter(~pl.col("is_return"))
    largest_lines = sales.group_by("receipt_id").agg(pl.col("net_eur").max())
    return [(number(largest_lines["net_eur"].mean()),)]


def _case_137(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 137 from base data, independently of SQL."""
    g = grouped(d.window("2025-01-01", "2025-12-31", "HU"), ["region_name", "store_id"])
    return (
        g.sort(["region_name", "net_eur", "store_id"], descending=[False, True, False])
        .unique(subset=["region_name"], keep="first", maintain_order=True)
        .rows()
    )


def _case_138(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 138 from base data, independently of SQL."""
    f = d.window("2025-01-01", "2025-12-31", "HU")
    g = grouped(f, ["store_id"]).sort(["net_eur", "store_id"], descending=[True, False])
    return [(number(g.head(3)["net_eur"].sum()) / number(f["net_eur"].sum()),)]


def _case_139(d: ReferenceData) -> Sequence[tuple[object, ...]]:
    """Compute case 139 from base data, independently of SQL."""
    f = d.all_lines.filter(
        ~pl.col("is_test_store")
        & ~pl.col("is_return")
        & pl.col("sales_date").is_between(dt.date(2025, 10, 1), dt.date(2025, 12, 31))
    )
    v = []
    for c in ["AT", "HU"]:
        g = f.filter(pl.col("country_code") == c)
        v.append(
            (
                c,
                g.filter(pl.col("is_cancelled"))["receipt_id"].n_unique()
                / g["receipt_id"].n_unique(),
            )
        )
    return v


def expected(case_id: str, d: ReferenceData) -> list[tuple[object, ...]]:
    """Recompute the selected case using its independent arithmetic."""
    calculators = {
        "101": _case_101,
        "102": _case_102,
        "103": _case_103,
        "104": _case_104,
        "105": _case_105,
        "106": _case_106,
        "107": _case_107,
        "108": _case_108,
        "109": _case_109,
        "110": _case_110,
        "111": _case_111,
        "112": _case_112,
        "113": _case_113,
        "114": _case_114,
        "115": _case_115,
        "116": _case_116,
        "117": _case_117,
        "118": _case_118,
        "119": _case_119,
        "120": _case_120,
        "121": _case_121,
        "122": _case_122,
        "123": _case_123,
        "124": _case_124,
        "125": _case_125,
        "126": _case_126,
        "127": _case_127,
        "128": _case_128,
        "130": _case_130,
        "131": _case_131,
        "132": _case_132,
        "133": _case_133,
        "134": _case_134,
        "135": _case_135,
        "136": _case_136,
        "137": _case_137,
        "138": _case_138,
        "139": _case_139,
    }
    return list(calculators[case_id](d))
