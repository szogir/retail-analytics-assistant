"""Tests for the holiday calendar and store closures (data_gen.closures)."""

import datetime as dt

import pytest

from data_gen.closures import (
    build_dim_holiday,
    closed_holidays,
    easter_sunday,
    is_open,
)


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2023, dt.date(2023, 4, 9)),
        (2024, dt.date(2024, 3, 31)),
        (2025, dt.date(2025, 4, 20)),
        (2026, dt.date(2026, 4, 5)),
    ],
)
def test_easter_sunday_matches_known_dates(year: int, expected: dt.date) -> None:
    assert easter_sunday(year) == expected


def _holidays_2025() -> dict[tuple[str, dt.date], str]:
    rows = build_dim_holiday(dt.date(2025, 1, 1), dt.date(2025, 12, 31))
    return {(row.country_code, row.holiday_date): row.holiday_name for row in rows}


def test_movable_holidays_follow_easter_2025() -> None:
    holidays = _holidays_2025()
    assert holidays[("HU", dt.date(2025, 4, 18))] == "Good Friday"
    assert holidays[("HU", dt.date(2025, 4, 21))] == "Easter Monday"
    assert holidays[("AT", dt.date(2025, 5, 29))] == "Ascension Day"
    assert holidays[("AT", dt.date(2025, 6, 9))] == "Whit Monday"
    assert holidays[("AT", dt.date(2025, 6, 19))] == "Corpus Christi"


def test_good_friday_is_only_a_hungarian_holiday() -> None:
    holidays = _holidays_2025()
    assert ("AT", dt.date(2025, 4, 18)) not in holidays


def test_each_country_has_13_holidays_in_2025() -> None:
    holidays = _holidays_2025()
    assert sum(1 for country, _ in holidays if country == "HU") == 13
    assert sum(1 for country, _ in holidays if country == "AT") == 13


def test_holidays_outside_the_range_are_left_out() -> None:
    rows = build_dim_holiday(dt.date(2025, 3, 1), dt.date(2025, 3, 31))
    assert [(r.country_code, r.holiday_date) for r in rows] == [("HU", dt.date(2025, 3, 15))]


def test_stores_are_closed_on_holidays_in_their_country_only() -> None:
    closed = closed_holidays(build_dim_holiday(dt.date(2025, 1, 1), dt.date(2025, 12, 31)))
    saturday = dt.date(2025, 3, 15)  # Hungarian National Day
    assert not is_open("HU", saturday, closed)
    assert is_open("AT", saturday, closed)  # an ordinary Austrian Saturday


def test_austrian_stores_are_closed_on_sundays_but_hungarian_stores_are_open() -> None:
    closed = closed_holidays([])
    sunday = dt.date(2025, 3, 2)
    assert sunday.weekday() == 6
    assert not is_open("AT", sunday, closed)
    assert is_open("HU", sunday, closed)
