"""Tests for the golden set: the files are valid and every reference SQL really works.

A broken reference SQL would silently turn into a wrong "expected answer", so the SQL of
every case is executed against the full synthetic database.
"""

import datetime as dt

import duckdb
import pytest

from evals.golden import GoldenCase, load_golden_set

CASES = load_golden_set()


def test_golden_set_has_at_least_ten_cases_with_unique_ids() -> None:
    assert len(CASES) >= 10
    assert len({case.id for case in CASES}) == len(CASES)


def test_every_case_uses_the_fixed_as_of_date() -> None:
    # The data ends on 2026-10-03; "today" for all cases is the following day.
    assert {case.as_of_date for case in CASES} == {dt.date(2026, 10, 4)}


def test_every_case_documents_why_it_exists() -> None:
    for case in CASES:
        assert case.notes.strip(), f"case {case.id} has no notes"
        assert case.questions.en.strip()


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_reference_sql_runs_and_returns_a_value(
    case: GoldenCase, db: duckdb.DuckDBPyConnection
) -> None:
    rows = db.execute(case.reference_sql).fetchall()
    assert rows, f"case {case.id} returned no rows"
    assert any(value is not None for row in rows for value in row), (
        f"case {case.id} returned only NULLs"
    )


def test_net_sales_of_case_001_are_plausible(db: duckdb.DuckDBPyConnection) -> None:
    # A sanity check of the answer itself: one positive row per country.
    case = next(c for c in CASES if c.id == "001")
    rows = db.execute(case.reference_sql).fetchall()
    assert [row[0] for row in rows] == ["AT", "HU"]
    assert all(row[1] > 0 for row in rows)
