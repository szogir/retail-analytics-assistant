"""Synthetic data generator for the fictional discount grocery chain.

What it does: builds the dimension tables (`dim_date`, `dim_store`, `dim_product`) and
writes them into a DuckDB file. The fact and FX tables are added in a later step.

Why it exists: the project proves that a semantic layer improves text-to-SQL accuracy.
To measure that, we need data where the correct answer is known and where the classic
traps (test stores, cancelled receipts, mixed currencies, VAT) exist on purpose. Real
data cannot give us that. Everything here is fictional and only *shaped like* reality:
VAT rates and prices are simplified and are not tax-law references.

Where it sits in the pipeline: before everything. The assistant, the golden set and the
evaluation all read the database this script produces (`data/retail.duckdb`).

Run: `uv run python -m data_gen.generate`
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np

SEED = 42
DEFAULT_DB_PATH = Path("data") / "retail.duckdb"

# Design note: the fiscal year starts on 1 March (not on 1 January) so that "fiscal"
# and "calendar" are different things. A question like "last fiscal month" then has a
# real trap in it. The alternative, fiscal year = calendar year, would make the
# `fiscal_*` columns decorative.
FISCAL_YEAR_START_MONTH = 3
DATA_START = dt.date(2025, 3, 1)
DATA_DAYS = 365  # 2025-03-01 .. 2026-02-28, exactly one fiscal year

PRIVATE_LABEL_BRAND = "Daily Choice"

# Fixed list instead of `strftime("%A")`: strftime depends on the machine locale, and the
# database must be identical on every machine.
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


# --- Static reference data ----------------------------------------------------------
# Kept as plain, readable tables instead of generated text: we need exact English /
# Hungarian pairs, and a reviewer can read them in one go.


@dataclass(frozen=True)
class StoreSpec:
    """One row of the fixed store list."""

    name: str
    city: str
    country_code: str  # "HU" or "AT"
    region_id: int
    region_name: str
    is_test_store: bool = False


# Design note: stores are a fixed list, not random. Names must look real and the
# permission demo needs known regions (one HU region is "anna's"). Randomness would add
# nothing here. The alternative (Faker) gives unrealistic names and a new dependency.
STORES: list[StoreSpec] = [
    StoreSpec("Budapest Újpest", "Budapest", "HU", 1, "Budapest"),
    StoreSpec("Budapest Kőbánya", "Budapest", "HU", 1, "Budapest"),
    StoreSpec("Budapest Csepel", "Budapest", "HU", 1, "Budapest"),
    # Trap 2: a test store that real analyses must exclude.
    StoreSpec("Budapest Teszt Bolt", "Budapest", "HU", 1, "Budapest", is_test_store=True),
    StoreSpec("Székesfehérvár Észak", "Székesfehérvár", "HU", 2, "Közép-Dunántúl"),
    StoreSpec("Tatabánya Centrum", "Tatabánya", "HU", 2, "Közép-Dunántúl"),
    StoreSpec("Veszprém Dél", "Veszprém", "HU", 2, "Közép-Dunántúl"),
    StoreSpec("Szeged Belváros", "Szeged", "HU", 3, "Dél-Alföld"),
    StoreSpec("Kecskemét Kelet", "Kecskemét", "HU", 3, "Dél-Alföld"),
    StoreSpec("Békéscsaba Centrum", "Békéscsaba", "HU", 3, "Dél-Alföld"),
    StoreSpec("Miskolc Diósgyőr", "Miskolc", "HU", 4, "Észak-Magyarország"),
    StoreSpec("Eger Pláza", "Eger", "HU", 4, "Észak-Magyarország"),
    StoreSpec("Wien Favoriten", "Wien", "AT", 5, "Wien"),
    StoreSpec("Wien Donaustadt", "Wien", "AT", 5, "Wien"),
    StoreSpec("Wien Floridsdorf", "Wien", "AT", 5, "Wien"),
    StoreSpec("St. Pölten Süd", "St. Pölten", "AT", 6, "Niederösterreich"),
    StoreSpec("Wiener Neustadt", "Wiener Neustadt", "AT", 6, "Niederösterreich"),
    StoreSpec("Krems Zentrum", "Krems", "AT", 6, "Niederösterreich"),
    StoreSpec("Graz Nord", "Graz", "AT", 7, "Steiermark"),
    StoreSpec("Leoben", "Leoben", "AT", 7, "Steiermark"),
]


@dataclass(frozen=True)
class CategorySpec:
    """A product category with the data the generator needs about it."""

    name_en: str
    name_hu: str
    brand: str  # one fictional branded label per category
    price_low_eur: float
    price_high_eur: float
    # Simplified VAT rates in percent. They differ by country AND category so that the
    # "net = gross - discount - VAT" trap (trap 4) cannot be solved with one constant.
    vat_hu_percent: int
    vat_at_percent: int
    # (English name, Hungarian name) pairs; each pair becomes two products
    # (branded + private label).
    items: list[tuple[str, str]]


CATEGORIES: list[CategorySpec] = [
    CategorySpec(
        "Dairy",
        "Tejtermékek",
        "Meadowgold",
        0.8,
        5.0,
        18,
        10,
        [
            ("Whole milk 1 l", "Teljes tej 1 l"),
            ("Semi-skimmed milk 1 l", "Félzsíros tej 1 l"),
            ("Natural yoghurt 150 g", "Natúr joghurt 150 g"),
            ("Sour cream 175 g", "Tejföl 175 g"),
            ("Cottage cheese 250 g", "Túró 250 g"),
            ("Edam cheese slices 150 g", "Edami sajt szeletelt 150 g"),
            ("Butter 250 g", "Vaj 250 g"),
            ("Mozzarella 125 g", "Mozzarella 125 g"),
        ],
    ),
    CategorySpec(
        "Bakery",
        "Pékáru",
        "Goldcrust",
        0.6,
        4.0,
        18,
        10,
        [
            ("White bread 500 g", "Fehér kenyér 500 g"),
            ("Rye bread 500 g", "Rozskenyér 500 g"),
            ("Croissant", "Croissant"),
            ("Bread rolls 6 pcs", "Zsemle 6 db"),
            ("Sliced toast bread 500 g", "Szeletelt kenyér 500 g"),
            ("Salty sticks 200 g", "Sós rúd 200 g"),
            ("Sponge cake 300 g", "Piskóta 300 g"),
            ("Baguette", "Bagett"),
        ],
    ),
    CategorySpec(
        "Fresh produce",
        "Zöldség és gyümölcs",
        "Greenfield",
        0.7,
        3.5,
        5,
        10,
        [
            ("Bananas 1 kg", "Banán 1 kg"),
            ("Apples 1 kg", "Alma 1 kg"),
            ("Tomatoes 500 g", "Paradicsom 500 g"),
            ("Cucumber", "Uborka"),
            ("Potatoes 2 kg", "Burgonya 2 kg"),
            ("Onions 1 kg", "Vöröshagyma 1 kg"),
            ("Carrots 1 kg", "Sárgarépa 1 kg"),
            ("Peppers 500 g", "Paprika 500 g"),
        ],
    ),
    CategorySpec(
        "Meat and deli",
        "Hús és felvágott",
        "Farmhouse",
        1.5,
        8.0,
        5,
        10,
        [
            ("Chicken breast 500 g", "Csirkemell 500 g"),
            ("Minced pork 500 g", "Darált sertéshús 500 g"),
            ("Pork chops 500 g", "Sertéskaraj 500 g"),
            ("Smoked sausage 200 g", "Füstölt kolbász 200 g"),
            ("Ham slices 100 g", "Szeletelt sonka 100 g"),
            ("Salami 100 g", "Szalámi 100 g"),
            ("Beef for goulash 500 g", "Marhagulyáshús 500 g"),
            ("Turkey breast 500 g", "Pulykamell 500 g"),
        ],
    ),
    CategorySpec(
        "Beverages",
        "Italok",
        "Clearspring",
        0.6,
        7.0,
        27,
        20,
        [
            ("Mineral water 1.5 l", "Ásványvíz 1,5 l"),
            ("Orange juice 1 l", "Narancslé 1 l"),
            ("Cola 1.5 l", "Kóla 1,5 l"),
            ("Lager beer 0.5 l", "Világos sör 0,5 l"),
            ("Red wine 0.75 l", "Vörösbor 0,75 l"),
            ("Apple juice 1 l", "Almalé 1 l"),
            ("Iced tea 1.5 l", "Jeges tea 1,5 l"),
            ("Energy drink 250 ml", "Energiaital 250 ml"),
        ],
    ),
    CategorySpec(
        "Hot drinks",
        "Meleg italok",
        "Morningbrew",
        1.2,
        7.0,
        27,
        20,
        [
            ("Ground coffee 250 g", "Őrölt kávé 250 g"),
            ("Instant coffee 100 g", "Instant kávé 100 g"),
            ("Black tea 25 bags", "Fekete tea 25 filter"),
            ("Green tea 20 bags", "Zöld tea 20 filter"),
            ("Hot chocolate 300 g", "Forró csoki 300 g"),
            ("Coffee capsules 10 pcs", "Kávékapszula 10 db"),
            ("Herbal tea 20 bags", "Gyógytea 20 filter"),
            ("Coffee beans 500 g", "Szemes kávé 500 g"),
        ],
    ),
    CategorySpec(
        "Pantry",
        "Tartós élelmiszer",
        "Homestead",
        0.7,
        4.5,
        27,
        10,
        [
            ("Spaghetti 500 g", "Spagetti 500 g"),
            ("Rice 1 kg", "Rizs 1 kg"),
            ("Flour 1 kg", "Liszt 1 kg"),
            ("Sugar 1 kg", "Cukor 1 kg"),
            ("Sunflower oil 1 l", "Napraforgóolaj 1 l"),
            ("Canned tomatoes 400 g", "Konzerv paradicsom 400 g"),
            ("Canned corn 340 g", "Konzerv kukorica 340 g"),
            ("Ground paprika 100 g", "Őrölt paprika 100 g"),
        ],
    ),
    CategorySpec(
        "Frozen food",
        "Fagyasztott termékek",
        "Frostbite",
        1.5,
        5.5,
        27,
        10,
        [
            ("Frozen peas 450 g", "Fagyasztott zöldborsó 450 g"),
            ("Frozen pizza 350 g", "Fagyasztott pizza 350 g"),
            ("Ice cream 1 l", "Fagylalt 1 l"),
            ("Fish fingers 250 g", "Halrudak 250 g"),
            ("Frozen spinach 450 g", "Fagyasztott spenót 450 g"),
            ("Frozen fries 750 g", "Fagyasztott hasábburgonya 750 g"),
            ("Frozen berries 300 g", "Fagyasztott erdei gyümölcs 300 g"),
            ("Frozen gnocchi 500 g", "Fagyasztott gnocchi 500 g"),
        ],
    ),
    CategorySpec(
        "Snacks and sweets",
        "Snackek és édességek",
        "Crunchy Joe",
        0.9,
        3.5,
        27,
        10,
        [
            ("Potato chips 150 g", "Burgonyachips 150 g"),
            ("Milk chocolate 100 g", "Tejcsokoládé 100 g"),
            ("Salted peanuts 200 g", "Sós mogyoró 200 g"),
            ("Gummy bears 200 g", "Gumicukor 200 g"),
            ("Biscuits 300 g", "Keksz 300 g"),
            ("Wafers 150 g", "Ostya 150 g"),
            ("Muesli bars 6 pcs", "Müzliszelet 6 db"),
            ("Popcorn 100 g", "Popcorn 100 g"),
        ],
    ),
    CategorySpec(
        "Household",
        "Háztartás",
        "Brightly",
        0.8,
        9.0,
        27,
        20,
        [
            ("Dish soap 500 ml", "Mosogatószer 500 ml"),
            ("Laundry detergent 2 l", "Mosószer 2 l"),
            ("Toilet paper 8 rolls", "WC-papír 8 tekercs"),
            ("Paper towels 2 rolls", "Papírtörlő 2 tekercs"),
            ("Bin bags 35 l", "Szemeteszsák 35 l"),
            ("Sponges 5 pcs", "Mosogatószivacs 5 db"),
            ("Glass cleaner 500 ml", "Ablaktisztító 500 ml"),
            ("LED light bulb", "LED izzó"),
        ],
    ),
    CategorySpec(
        "Personal care",
        "Testápolás",
        "Purelle",
        0.9,
        6.0,
        27,
        20,
        [
            ("Shampoo 400 ml", "Sampon 400 ml"),
            ("Shower gel 250 ml", "Tusfürdő 250 ml"),
            ("Toothpaste 75 ml", "Fogkrém 75 ml"),
            ("Deodorant 150 ml", "Dezodor 150 ml"),
            ("Liquid hand soap 300 ml", "Folyékony szappan 300 ml"),
            ("Cotton pads 100 pcs", "Vattakorong 100 db"),
            ("Razors 4 pcs", "Borotva 4 db"),
            ("Hand cream 75 ml", "Kézkrém 75 ml"),
        ],
    ),
    CategorySpec(
        "Pet supplies",
        "Kisállat-termékek",
        "Happypaw",
        0.9,
        9.0,
        27,
        20,
        [
            ("Dog food 400 g", "Kutyaeledel 400 g"),
            ("Cat food 85 g", "Macskaeledel 85 g"),
            ("Cat litter 5 kg", "Macskaalom 5 kg"),
            ("Dog treats 100 g", "Jutalomfalat kutyáknak 100 g"),
            ("Bird seed 500 g", "Madáreleség 500 g"),
            ("Fish food 50 g", "Haleledel 50 g"),
            ("Chew bone", "Rágócsont"),
            ("Pet shampoo 250 ml", "Kisállat-sampon 250 ml"),
        ],
    ),
]

# Private-label products are cheaper than the branded equivalent.
PRIVATE_LABEL_PRICE_FACTOR = 0.8


# --- Row types ----------------------------------------------------------------------
# Plain dataclasses instead of dicts or DataFrames: every field is named and typed, so
# mypy catches mistakes and the code reads like the table definition.


@dataclass(frozen=True)
class DateRow:
    """One calendar day with its fiscal attributes."""

    date: dt.date
    weekday: str
    fiscal_week: int
    fiscal_month: int
    fiscal_year: int


@dataclass(frozen=True)
class StoreRow:
    """One store."""

    store_id: int
    store_name: str
    city: str
    country_code: str
    region_id: int
    region_name: str
    is_test_store: bool


@dataclass(frozen=True)
class ProductRow:
    """One product.

    `base_price_eur` and `category_key` are NOT columns of `dim_product`. They are
    generator-internal: the fact generator (next step) needs a price and a VAT rate per
    product, and keeping them here avoids a second source of truth.
    """

    product_id: int
    name_en: str
    name_hu: str
    category_en: str
    category_hu: str
    is_private_label: bool
    base_price_eur: float
    category_key: str


# --- Builders -----------------------------------------------------------------------


def fiscal_year_start(day: dt.date) -> dt.date:
    """Return the first day of the fiscal year that contains `day`.

    Args:
        day: Any calendar date.

    Returns:
        The 1 March on or before `day`.
    """
    year = day.year if day.month >= FISCAL_YEAR_START_MONTH else day.year - 1
    return dt.date(year, FISCAL_YEAR_START_MONTH, 1)


def build_dim_date(start: dt.date = DATA_START, days: int = DATA_DAYS) -> list[DateRow]:
    """Build the calendar dimension.

    Conventions (also written into docs/decisions.md):
    - `fiscal_year` is named after the calendar year in which it STARTS
      (2025-03-01 .. 2026-02-28 is fiscal year 2025).
    - `fiscal_month` is 1..12, March = 1.
    - `fiscal_week` counts 7-day blocks from the fiscal year start, so it is 1..53 and
      week 53 is a single day. Simple and explainable beats ISO-week subtleties here.

    Args:
        start: First day of the calendar.
        days: Number of consecutive days.

    Returns:
        One DateRow per day, in date order.
    """
    rows: list[DateRow] = []
    for offset in range(days):
        day = start + dt.timedelta(days=offset)
        year_start = fiscal_year_start(day)
        rows.append(
            DateRow(
                date=day,
                weekday=WEEKDAY_NAMES[day.weekday()],
                fiscal_week=(day - year_start).days // 7 + 1,
                fiscal_month=(day.month - FISCAL_YEAR_START_MONTH) % 12 + 1,
                fiscal_year=year_start.year,
            )
        )
    return rows


def build_dim_store() -> list[StoreRow]:
    """Build the store dimension from the fixed list.

    Returns:
        One StoreRow per store; `store_id` is 1..N in list order.
    """
    return [
        StoreRow(
            store_id=index,
            store_name=spec.name,
            city=spec.city,
            country_code=spec.country_code,
            region_id=spec.region_id,
            region_name=spec.region_name,
            is_test_store=spec.is_test_store,
        )
        for index, spec in enumerate(STORES, start=1)
    ]


def build_dim_product(rng: np.random.Generator) -> list[ProductRow]:
    """Build the product dimension: every item exists as branded and private label.

    Why: the only random part is the base price. Everything else is fixed, so the
    catalogue is readable and the HU/EN names always match.

    Design note: half of the catalogue is private label (a discounter has a high share).
    The alternative, a random 30% flag, would make the share vary with the seed and
    leave some items without a branded or a private-label twin.

    Args:
        rng: Seeded random generator (one stream for the whole script).

    Returns:
        One ProductRow per product, `product_id` is 1..N.
    """
    rows: list[ProductRow] = []
    product_id = 1
    for category in CATEGORIES:
        for name_en, name_hu in category.items:
            raw_price = rng.uniform(category.price_low_eur, category.price_high_eur)
            for is_private_label in (False, True):
                brand = PRIVATE_LABEL_BRAND if is_private_label else category.brand
                factor = PRIVATE_LABEL_PRICE_FACTOR if is_private_label else 1.0
                # Round to 5 cents: shelf prices do not have arbitrary decimals.
                price = round(raw_price * factor * 20) / 20
                rows.append(
                    ProductRow(
                        product_id=product_id,
                        name_en=f"{name_en} ({brand})",
                        name_hu=f"{name_hu} ({brand})",
                        category_en=category.name_en,
                        category_hu=category.name_hu,
                        is_private_label=is_private_label,
                        base_price_eur=price,
                        category_key=category.name_en,
                    )
                )
                product_id += 1
    return rows


# --- Writing to DuckDB --------------------------------------------------------------

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
]


def write_dimensions(db_path: Path, rng: np.random.Generator) -> None:
    """Create the database file and fill the dimension tables.

    Why: an existing file is deleted first, so the result never depends on what an
    earlier run left behind (same seed -> same content, every time).

    Args:
        db_path: Where to write the DuckDB file.
        rng: Seeded random generator.

    Raises:
        duckdb.Error: If a table cannot be created or filled.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)

    dates = build_dim_date()
    stores = build_dim_store()
    products = build_dim_product(rng)

    connection = duckdb.connect(str(db_path))
    try:
        for statement in DDL_STATEMENTS:
            connection.execute(statement)
        # Parameterised inserts: values never become part of the SQL text.
        connection.executemany(
            "INSERT INTO dim_date VALUES (?, ?, ?, ?, ?)",
            [(d.date, d.weekday, d.fiscal_week, d.fiscal_month, d.fiscal_year) for d in dates],
        )
        connection.executemany(
            "INSERT INTO dim_store VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    s.store_id,
                    s.store_name,
                    s.city,
                    s.country_code,
                    s.region_id,
                    s.region_name,
                    s.is_test_store,
                )
                for s in stores
            ],
        )
        connection.executemany(
            "INSERT INTO dim_product VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    p.product_id,
                    p.name_en,
                    p.name_hu,
                    p.category_en,
                    p.category_hu,
                    p.is_private_label,
                )
                for p in products
            ],
        )
    finally:
        connection.close()


def main() -> None:
    """Generate the database with the fixed seed."""
    rng = np.random.default_rng(SEED)
    write_dimensions(DEFAULT_DB_PATH, rng)
    print(f"Wrote dimension tables to {DEFAULT_DB_PATH}")


if __name__ == "__main__":
    main()
