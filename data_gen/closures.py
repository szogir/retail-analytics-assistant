"""Public holidays and store closures of the fictional chain (Hungary and Austria).

What it does: computes the public holidays of each country for a date range, and answers
the question "are the stores of this country open on this day?".

Why it exists: on a closed day a store has no sales rows at all. Real data behaves the
same, and it creates a trap: "average sales per day" can be divided by all calendar days
or only by trading days. The same holiday list is also written to `dim_holiday`, so
there is one single source of truth for "why was there no sale that day".

Where it sits in the pipeline: input of the sales generator (closed days) and of the
database writer (`dim_holiday`).

Simplifications: only the main national holidays are included, bridge days and local
holidays are not. This is not an official calendar.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

# Design note: in Austria shops are closed on Sundays by law; in Hungary they are open.
# This is a trading rule, not a holiday, so it is NOT in `dim_holiday`.
SUNDAY_CLOSED_COUNTRIES = frozenset({"AT"})
SUNDAY = 6  # date.weekday(): Monday = 0 ... Sunday = 6


@dataclass(frozen=True)
class HolidayRule:
    """How to find a holiday in a given year.

    Exactly one of the two ways is used: a fixed month/day, or an offset in days from
    Easter Sunday (needed because Easter moves every year).
    """

    name: str
    month: int | None = None
    day: int | None = None
    easter_offset_days: int | None = None


@dataclass(frozen=True)
class HolidayRow:
    """One row of `dim_holiday`."""

    country_code: str
    holiday_date: dt.date
    holiday_name: str


HOLIDAY_RULES: dict[str, list[HolidayRule]] = {
    "HU": [
        HolidayRule("New Year's Day", month=1, day=1),
        HolidayRule("National Day (1848 Revolution)", month=3, day=15),
        HolidayRule("Good Friday", easter_offset_days=-2),
        HolidayRule("Easter Sunday", easter_offset_days=0),
        HolidayRule("Easter Monday", easter_offset_days=1),
        HolidayRule("Labour Day", month=5, day=1),
        HolidayRule("Whit Sunday", easter_offset_days=49),
        HolidayRule("Whit Monday", easter_offset_days=50),
        HolidayRule("St Stephen's Day", month=8, day=20),
        HolidayRule("Republic Day (1956 Revolution)", month=10, day=23),
        HolidayRule("All Saints' Day", month=11, day=1),
        HolidayRule("Christmas Day", month=12, day=25),
        HolidayRule("Boxing Day", month=12, day=26),
    ],
    "AT": [
        HolidayRule("New Year's Day", month=1, day=1),
        HolidayRule("Epiphany", month=1, day=6),
        HolidayRule("Easter Monday", easter_offset_days=1),
        HolidayRule("Labour Day", month=5, day=1),
        HolidayRule("Ascension Day", easter_offset_days=39),
        HolidayRule("Whit Monday", easter_offset_days=50),
        HolidayRule("Corpus Christi", easter_offset_days=60),
        HolidayRule("Assumption Day", month=8, day=15),
        HolidayRule("National Day", month=10, day=26),
        HolidayRule("All Saints' Day", month=11, day=1),
        HolidayRule("Immaculate Conception", month=12, day=8),
        HolidayRule("Christmas Day", month=12, day=25),
        HolidayRule("St Stephen's Day", month=12, day=26),
    ],
}


def easter_sunday(year: int) -> dt.date:
    """Return the date of Easter Sunday (Gregorian calendar).

    Why: Easter, Whit Monday and Corpus Christi move every year. A formula is safer than
    typing the dates in by hand (the typo risk grows with every year we add).

    Design note: this is the "anonymous Gregorian algorithm" (Meeus/Jones/Butcher).
    The alternative, `dateutil.easter`, would add a dependency for ten lines of code.
    The unit test checks it against known dates.

    Args:
        year: A year after 1583.

    Returns:
        The date of Easter Sunday in that year.
    """
    golden = year % 19
    century, year_in_century = divmod(year, 100)
    leap_century, century_rest = divmod(century, 4)
    moon_shift = (century + 8) // 25
    correction = (century - moon_shift + 1) // 3
    epact = (19 * golden + century - leap_century - correction + 15) % 30
    leap_year, year_rest = divmod(year_in_century, 4)
    weekday_shift = (32 + 2 * century_rest + 2 * leap_year - epact - year_rest) % 7
    adjustment = (golden + 11 * epact + 22 * weekday_shift) // 451
    month, day_minus_one = divmod(epact + weekday_shift - 7 * adjustment + 114, 31)
    return dt.date(year, month, day_minus_one + 1)


def _holiday_date(rule: HolidayRule, year: int) -> dt.date:
    if rule.easter_offset_days is not None:
        return easter_sunday(year) + dt.timedelta(days=rule.easter_offset_days)
    # A rule without an Easter offset must carry a fixed month and day.
    if rule.month is None or rule.day is None:
        raise ValueError(f"holiday rule has neither an Easter offset nor a date: {rule.name}")
    return dt.date(year, rule.month, rule.day)


def build_dim_holiday(start: dt.date, end: dt.date) -> list[HolidayRow]:
    """Build the holiday dimension for a date range.

    Args:
        start: First day of the range (inclusive).
        end: Last day of the range (inclusive).

    Returns:
        Holidays of both countries inside the range, sorted by country and date.
    """
    rows: list[HolidayRow] = []
    for country_code, rules in HOLIDAY_RULES.items():
        for year in range(start.year, end.year + 1):
            for rule in rules:
                day = _holiday_date(rule, year)
                if start <= day <= end:
                    rows.append(HolidayRow(country_code, day, rule.name))
    return sorted(rows, key=lambda row: (row.country_code, row.holiday_date))


def closed_holidays(holidays: list[HolidayRow]) -> frozenset[tuple[str, dt.date]]:
    """Return the holidays as a set of (country, date) for fast lookups."""
    return frozenset((row.country_code, row.holiday_date) for row in holidays)


def is_open(country_code: str, day: dt.date, closed: frozenset[tuple[str, dt.date]]) -> bool:
    """Return True if the stores of a country trade on a given day.

    Args:
        country_code: "HU" or "AT".
        day: The calendar day.
        closed: Result of `closed_holidays`.

    Returns:
        False on public holidays, and on Sundays in countries that close on Sundays.
    """
    if (country_code, day) in closed:
        return False
    return not (country_code in SUNDAY_CLOSED_COUNTRIES and day.weekday() == SUNDAY)
