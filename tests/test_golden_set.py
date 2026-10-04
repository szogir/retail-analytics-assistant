"""Tests for the golden set: the files are valid and every reference SQL really works.

A broken reference SQL would silently turn into a wrong "expected answer", so the SQL of
every case that expects a table is executed against the full synthetic database.
"""

import datetime as dt
from pathlib import Path

import duckdb
import pytest
from pydantic import ValidationError

from evals.golden import GoldenCase, load_golden_set

CASES = load_golden_set()
# Clarification and refusal cases have no reference SQL: their correct answer is no table.
TABLE_CASES = [case for case in CASES if case.expected.kind in ("result", "result_scoped")]


def test_golden_set_has_at_least_25_cases_with_unique_ids() -> None:
    assert len(CASES) >= 25
    assert len({case.id for case in CASES}) == len(CASES)


def test_every_case_uses_the_fixed_as_of_date() -> None:
    # The data ends on 2026-10-03; "today" for all cases is the following day.
    assert {case.as_of_date for case in CASES} == {dt.date(2026, 10, 4)}


def test_every_case_documents_why_it_exists() -> None:
    for case in CASES:
        assert case.notes.strip(), f"case {case.id} has no notes"
        assert case.questions.en.strip()


def test_every_case_has_a_hungarian_question() -> None:
    for case in CASES:
        assert case.questions.hu and case.questions.hu.strip(), f"case {case.id} has no hu"


def test_golden_set_covers_every_expected_kind_and_trap() -> None:
    kinds = {case.expected.kind for case in CASES}
    assert {"result", "clarification", "refusal"} <= kinds
    assert sum(case.expected.kind == "clarification" for case in CASES) >= 2
    assert sum(case.category == "security" for case in CASES) >= 4
    # Traps 1-5 of the data generator must each be touched by at least one case.
    touched = {trap for case in CASES for trap in case.traps}
    assert {1, 2, 3, 4, 5} <= touched


@pytest.mark.parametrize("case", TABLE_CASES, ids=[case.id for case in TABLE_CASES])
def test_reference_sql_runs_and_returns_a_value(
    case: GoldenCase, db: duckdb.DuckDBPyConnection
) -> None:
    assert case.reference_sql is not None
    rows = db.execute(case.reference_sql).fetchall()
    assert rows, f"case {case.id} returned no rows"
    assert any(value is not None for row in rows for value in row), (
        f"case {case.id} returned only NULLs"
    )


def test_net_sales_of_case_001_are_plausible(db: duckdb.DuckDBPyConnection) -> None:
    # A sanity check of the answer itself: one positive row per country.
    case = next(c for c in CASES if c.id == "001")
    assert case.reference_sql is not None
    rows = db.execute(case.reference_sql).fetchall()
    assert [row[0] for row in rows] == ["AT", "HU"]
    assert all(row[1] > 0 for row in rows)


def _case_data(kind: str, reference_sql: str | None) -> dict[str, object]:
    data: dict[str, object] = {
        "id": "x",
        "questions": {"en": "q"},
        "user": "carla",
        "as_of_date": "2026-10-04",
        "category": "aggregation",
        "traps": [],
        "expected": {"kind": kind},
    }
    if reference_sql is not None:
        data["reference_sql"] = reference_sql
    return data


def test_a_table_case_without_sql_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GoldenCase.model_validate(_case_data("result", None))


def test_a_refusal_case_with_sql_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GoldenCase.model_validate(_case_data("refusal", "SELECT 1"))


def test_loader_rejects_missing_or_empty_folder(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_golden_set(tmp_path / "does_not_exist")
    with pytest.raises(FileNotFoundError):
        load_golden_set(tmp_path)  # exists, but holds no case file
