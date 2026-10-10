"""Unit tests for the heuristic failure analysis (no network, no database)."""

import json
from pathlib import Path

import pytest

from evals.failure_analysis import (
    HEURISTIC_NOTICE,
    analyze,
    analyze_run_file,
    classify_sql,
    render_markdown,
)

REFERENCE = (
    "SELECT SUM((f.gross_amount - f.discount_amount - f.vat_amount) / fx.eur_rate) "
    "FROM fact_sales f JOIN fx_rate fx ON fx.rate_date = f.sales_date "
    "JOIN dim_store s ON s.store_id = f.store_id "
    "WHERE NOT f.is_cancelled AND NOT s.is_test_store"
)


def test_net_formula_and_test_store_are_flagged() -> None:
    model = (
        "SELECT SUM((gross_amount - discount_amount) / eur_rate) FROM fact_sales "
        "JOIN fx_rate USING (currency) WHERE is_cancelled = FALSE"
    )
    labels = classify_sql(model, REFERENCE)
    assert "net_formula_no_vat" in labels
    assert "test_store_not_excluded" in labels
    assert "cancelled_not_excluded" not in labels


def test_fx_multiplication_is_flagged_as_wrong_direction() -> None:
    model = "SELECT SUM(vat_amount * fx.eur_rate), is_cancelled, is_test_store FROM t"
    assert "fx_direction" in classify_sql(model, REFERENCE)


def test_return_and_fiscal_rules_work_in_both_directions() -> None:
    reference = "SELECT 1 WHERE d.fiscal_year = 2025"
    model = "SELECT 1 WHERE NOT f.is_return AND d.year = 2025"
    labels = classify_sql(model, reference)
    assert "returns_wrongly_excluded" in labels
    assert "calendar_instead_of_fiscal" in labels
    assert "fiscal_instead_of_calendar" in classify_sql(
        "SELECT 1 WHERE fiscal_year = 1", "SELECT 1"
    )


def test_clean_sql_gets_the_unclassified_label() -> None:
    assert classify_sql(REFERENCE, REFERENCE) == ["other_unclassified"]


def _row(case_id: str, primary: bool, status: str = "answered", sql: str = "") -> dict[str, object]:
    return {
        "case_id": case_id,
        "expected_kind": "result",
        "status": status,
        "primary": primary,
        "sql": sql,
    }


def test_analyze_counts_questions_and_cases_separately() -> None:
    results: list[dict[str, object]] = [
        _row("001", False, sql="SELECT 1"),
        _row("001", False, sql="SELECT 1"),
        _row("002", True),
        _row("003", False, status="sql_error"),
        {**_row("004", False), "expected_kind": "refusal"},  # not a data question
    ]
    references = {"001": "SELECT 1 WHERE NOT s.is_test_store", "003": "SELECT 1"}
    analysis = analyze(results, references, mode="commented", repetitions=2)
    assert analysis.data_questions == 4
    assert analysis.failed_questions == 3
    assert analysis.failed_cases == 2
    assert analysis.by_question["test_store_not_excluded"] == 2
    assert analysis.by_case["test_store_not_excluded"] == 1
    assert analysis.by_question["sql_error"] == 1


def test_report_header_states_that_categories_are_heuristic() -> None:
    analysis = analyze([_row("001", False)], {"001": "SELECT 1"}, "naive", 1)
    text = render_markdown(analysis, Path("run.json"))
    assert HEURISTIC_NOTICE in text
    assert "Scope: data questions only: 1 questions" in text


def _write_run(path: Path, suite: str, mode: str) -> None:
    info = {"suite": suite, "mode": mode, "repetitions": 1}
    path.write_text(json.dumps({"info": info, "results": []}), encoding="utf-8")


def test_mode_mismatch_and_unsupported_runs_are_rejected(tmp_path: Path) -> None:
    run = tmp_path / "run.json"
    _write_run(run, "development", "naive")
    with pytest.raises(ValueError, match="expected 'commented'"):
        analyze_run_file(run, expected_mode="commented")
    # A holdout run is only analysed against the published copy, never the default folder.
    _write_run(run, "holdout", "naive")
    with pytest.raises(ValueError, match="only analysed against evals/holdout_published"):
        analyze_run_file(run)
    _write_run(run, "security", "naive")
    with pytest.raises(ValueError, match="only supports development and published holdout"):
        analyze_run_file(run)
