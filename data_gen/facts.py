"""Exchange rates and sales facts of the fictional discount grocery chain.

What it does: builds the `fx_rate` table (daily HUF/EUR rates) and the `fact_sales` table
(one row per receipt line), including the built-in traps the evaluation relies on.

Why it exists: this is the data every golden-set question is answered from. The traps are
deliberate and documented, so the correct answer to each question is known.

Where it sits in the pipeline: input of the database writer in `generate.py`.

Built-in traps (each is covered by golden-set cases):
1. Cancelled receipts: `is_cancelled` is TRUE on every line of ~2.5% of the receipts.
2. Test store: it has sales, but no real analysis may include them.
3. Mixed currencies: HU stores sell in HUF, AT stores in EUR. Amounts must be converted
   with the rate of the sales day before they are summed.
4. Net sales = gross - discount - VAT. VAT is INCLUDED in the gross amount.
5. Average basket = SUM(net) / COUNT(DISTINCT receipt), never an average of averages.

Exchange rate convention: `eur_rate` = units of the currency per 1 EUR (HUF is about
370, EUR is 1). To convert to euro, DIVIDE the amount by `eur_rate`.

Design note: everything is generated with vectorised numpy arrays, not Python loops over
rows. The alternative (a loop per receipt line) would take minutes for ~1.5 million
rows and would be harder to read than a handful of array operations.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import polars as pl

from data_gen.closures import is_open
from data_gen.dimensions import CATEGORIES, DateRow, ProductRow, StoreRow

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

# --- Exchange rates -----------------------------------------------------------------

HUF_RATE_CENTRE = 370.0
HUF_RATE_MAX_DEVIATION = 12.0  # the rate stays within 358 .. 382
HUF_RATE_PULL = 0.05  # how strongly the rate is pulled back to the centre each day
HUF_RATE_DAILY_NOISE = 1.5  # standard deviation of the random daily step


@dataclass(frozen=True)
class FxRow:
    """One row of `fx_rate`: units of `currency` per 1 EUR on `rate_date`."""

    rate_date: dt.date
    currency: str
    eur_rate: float


def build_fx_rates(dates: Sequence[DateRow], rng: np.random.Generator) -> list[FxRow]:
    """Build one HUF and one EUR rate for every day.

    Why: the rate moves every day, so a correct conversion must join the rate of the
    SALES day. A single constant would hide a whole class of mistakes.

    Design note: a mean-reverting random walk (each step = a pull towards 370 plus noise,
    cut off at +-12). A plain random walk could drift far away over 3.5 years.
    There are rows for weekends and holidays too, which keeps the join simple (real
    central-bank rates have gaps).

    Args:
        dates: The calendar days to cover.
        rng: Seeded random generator.

    Returns:
        Two rows per day: HUF (about 370) and EUR (always 1).
    """
    noise = rng.normal(0.0, HUF_RATE_DAILY_NOISE, size=len(dates))
    huf_rate = HUF_RATE_CENTRE
    rows: list[FxRow] = []
    for day, step in zip(dates, noise, strict=True):
        huf_rate += HUF_RATE_PULL * (HUF_RATE_CENTRE - huf_rate) + float(step)
        huf_rate = min(
            max(huf_rate, HUF_RATE_CENTRE - HUF_RATE_MAX_DEVIATION),
            HUF_RATE_CENTRE + HUF_RATE_MAX_DEVIATION,
        )
        rows.append(FxRow(day.date, "HUF", round(huf_rate, 2)))
        rows.append(FxRow(day.date, "EUR", 1.0))
    return rows


# --- Sales facts --------------------------------------------------------------------

# Volumes are scaled down on purpose: about 11 receipts per store per day gives ~1.5
# million lines over the whole period, which DuckDB handles in well under a second.
BASE_RECEIPTS_PER_STORE_DAY = 11.0
MEAN_EXTRA_LINES_PER_RECEIPT = 3.5  # lines = 1 + Poisson(3.5), so ~4.5 on average
TEST_STORE_SIZE_FACTOR = 0.3

# Monday .. Sunday. Saturday is the peak, as in real grocery retail.
WEEKDAY_FACTORS = np.array([0.90, 0.90, 0.95, 1.00, 1.15, 1.40, 0.70])
MONTH_FACTORS = {12: 1.35, 11: 1.10, 1: 0.90}  # December peak, quiet January

ANNUAL_VOLUME_GROWTH = 0.04  # more receipts every year
ANNUAL_PRICE_INFLATION = 0.03  # higher prices every year
# Hungarian shelf prices, expressed in euro, are lower than the Austrian ones.
COUNTRY_PRICE_FACTORS = {"HU": 0.85, "AT": 1.00}

CANCELLED_RECEIPT_SHARE = 0.025
RETURN_RECEIPT_SHARE = 0.015
PROMOTION_LINE_SHARE = 0.12
PROMOTION_DISCOUNT_RANGE = (0.05, 0.30)
MEAN_EXTRA_QUANTITY = 0.5  # quantity = 1 + Poisson(0.5), at most 6
MAX_QUANTITY = 6


def _round_to_currency(amounts: FloatArray, is_huf: npt.NDArray[np.bool_]) -> FloatArray:
    """Round to whole forints for HUF and to cents for EUR (that is how receipts look)."""
    return np.where(is_huf, np.round(amounts, 0), np.round(amounts, 2))


def build_fact_sales(
    dates: Sequence[DateRow],
    stores: Sequence[StoreRow],
    products: Sequence[ProductRow],
    fx_rates: Sequence[FxRow],
    holidays_closed: frozenset[tuple[str, dt.date]],
    rng: np.random.Generator,
) -> pl.DataFrame:
    """Build the `fact_sales` table.

    Steps (each one is a few array operations):
    1. For every (day, store) pair, draw the number of receipts. Closed days get zero.
    2. Expand to one entry per receipt and flag cancelled and returned receipts.
    3. Expand to one entry per receipt line: product, quantity.
    4. Compute the amounts in euro, convert them to the store currency with that day's
       rate, then derive discount and VAT. Returns get negative signs.

    Amount definitions (also the basis of the metric "net sales"):
    - `gross_amount` includes VAT, before discount.
    - `discount_amount` is the promotion discount on the gross amount.
    - `vat_amount` = (gross - discount) * rate / (100 + rate), i.e. the VAT contained in
      the amount the customer paid.
    - net sales = gross - discount - VAT.

    Args:
        dates: Calendar days to generate sales for.
        stores: Store dimension rows.
        products: Product dimension rows (with the generator-internal base price).
        fx_rates: Rows of `fx_rate`, used to convert euro to forint.
        holidays_closed: (country, date) pairs on which stores are closed.
        rng: Seeded random generator (a separate stream from the dimensions).

    Returns:
        A polars DataFrame with the columns of `fact_sales`.
    """
    day_count = len(dates)
    store_count = len(stores)
    product_count = len(products)

    # --- Per-day arrays ---
    day_dates = [row.date for row in dates]
    first_day = day_dates[0]
    years_since_start = np.array([(day - first_day).days / 365.25 for day in day_dates])
    weekday_factor = WEEKDAY_FACTORS[np.array([day.weekday() for day in day_dates])]
    month_factor = np.array([MONTH_FACTORS.get(day.month, 1.0) for day in day_dates])
    volume_trend = (1 + ANNUAL_VOLUME_GROWTH) ** years_since_start
    price_index = (1 + ANNUAL_PRICE_INFLATION) ** years_since_start
    huf_rate_by_day = np.array(
        [row.eur_rate for row in fx_rates if row.currency == "HUF"], dtype=np.float64
    )

    # --- Per-store arrays ---
    store_size = rng.uniform(0.6, 1.5, size=store_count)
    for index, store in enumerate(stores):
        if store.is_test_store:
            store_size[index] = TEST_STORE_SIZE_FACTOR
    store_is_huf = np.array([store.country_code == "HU" for store in stores])
    store_ids = np.array([store.store_id for store in stores], dtype=np.int64)

    # --- Step 1: receipts per (day, store) ---
    open_mask = np.array(
        [
            [is_open(store.country_code, day, holidays_closed) for store in stores]
            for day in day_dates
        ]
    )
    expected = (
        BASE_RECEIPTS_PER_STORE_DAY
        * store_size[np.newaxis, :]
        * (weekday_factor * month_factor * volume_trend)[:, np.newaxis]
    )
    receipts_per_cell = rng.poisson(expected) * open_mask

    # --- Step 2: one entry per receipt ---
    day_index_grid, store_index_grid = np.indices((day_count, store_count))
    receipt_day = np.repeat(day_index_grid.ravel(), receipts_per_cell.ravel())
    receipt_store = np.repeat(store_index_grid.ravel(), receipts_per_cell.ravel())
    receipt_count = len(receipt_day)
    receipt_ids = np.arange(1, receipt_count + 1, dtype=np.int64)
    receipt_cancelled = rng.random(receipt_count) < CANCELLED_RECEIPT_SHARE
    # A cancelled receipt is not also a return, so the two shares stay independent.
    receipt_return = (rng.random(receipt_count) < RETURN_RECEIPT_SHARE) & ~receipt_cancelled

    # --- Step 3: one entry per receipt line ---
    lines_per_receipt = 1 + rng.poisson(MEAN_EXTRA_LINES_PER_RECEIPT, size=receipt_count)
    line_count = int(lines_per_receipt.sum())
    line_receipt = np.repeat(np.arange(receipt_count), lines_per_receipt)
    first_line_of_receipt = np.cumsum(lines_per_receipt) - lines_per_receipt
    line_no = np.arange(line_count) - np.repeat(first_line_of_receipt, lines_per_receipt) + 1

    # Some products sell much more than others (log-normal popularity weights).
    popularity = rng.lognormal(0.0, 0.8, size=product_count)
    line_product = rng.choice(product_count, size=line_count, p=popularity / popularity.sum())
    quantity = np.minimum(
        1 + rng.poisson(MEAN_EXTRA_QUANTITY, size=line_count), MAX_QUANTITY
    ).astype(np.int64)

    # --- Step 4: amounts ---
    line_day = receipt_day[line_receipt]
    line_store = receipt_store[line_receipt]
    line_is_huf = store_is_huf[line_store]

    product_ids = np.array([product.product_id for product in products], dtype=np.int64)
    base_price_eur = np.array([product.base_price_eur for product in products])
    country_price_factor = np.where(
        line_is_huf, COUNTRY_PRICE_FACTORS["HU"], COUNTRY_PRICE_FACTORS["AT"]
    )
    gross_eur = (
        base_price_eur[line_product] * price_index[line_day] * country_price_factor * quantity
    )
    # Convert to the store currency with the rate of the sales day (EUR rate is 1).
    currency_rate = np.where(line_is_huf, huf_rate_by_day[line_day], 1.0)
    gross = _round_to_currency(gross_eur * currency_rate, line_is_huf)

    on_promotion = rng.random(line_count) < PROMOTION_LINE_SHARE
    discount_rate = rng.uniform(*PROMOTION_DISCOUNT_RANGE, size=line_count)
    discount = _round_to_currency(gross * discount_rate * on_promotion, line_is_huf)

    vat_hu = np.array([_category_vat(product, "HU") for product in products])
    vat_at = np.array([_category_vat(product, "AT") for product in products])
    vat_percent = np.where(line_is_huf, vat_hu[line_product], vat_at[line_product])
    vat = _round_to_currency((gross - discount) * vat_percent / (100.0 + vat_percent), line_is_huf)

    # Returns: the customer gives goods back, so units and all amounts are negative.
    sign = np.where(receipt_return[line_receipt], -1, 1)

    return pl.DataFrame(
        {
            "receipt_id": receipt_ids[line_receipt],
            "line_no": line_no.astype(np.int32),
            "sales_date": np.array(day_dates, dtype="datetime64[D]")[line_day],
            "store_id": store_ids[line_store],
            "product_id": product_ids[line_product],
            "quantity": (quantity * sign).astype(np.int32),
            "gross_amount": gross * sign,
            "discount_amount": discount * sign,
            "vat_amount": vat * sign,
            "currency": np.where(line_is_huf, "HUF", "EUR"),
            "is_return": receipt_return[line_receipt],
            "is_cancelled": receipt_cancelled[line_receipt],
        }
    )


def _category_vat(product: ProductRow, country_code: str) -> int:
    """Look up the VAT rate (percent) of a product's category for one country."""
    for category in CATEGORIES:
        if category.name_en == product.category_key:
            return category.vat_hu_percent if country_code == "HU" else category.vat_at_percent
    raise ValueError(f"unknown category: {product.category_key}")
