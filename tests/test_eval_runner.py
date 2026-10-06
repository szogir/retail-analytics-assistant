"""Tests for the evaluation: table comparison, report metrics and the runner (fake LLM)."""

from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import BaseModel

from evals.compare import compare_tables, values_equal
from evals.golden import GoldenCase, load_golden_set
from evals.report import (
    CaseResult,
    RunInfo,
    compare_to_baseline,
    load_baseline,
    percentile,
    render_report,
    save_baseline,
)
from evals.run_eval import run_evaluation
from retail_assistant.config import PROJECT_ROOT
from retail_assistant.llm.base import LLMError
from retail_assistant.llm.fake import FakeLLMClient
from retail_assistant.llm.profiles import load_profile
from retail_assistant.llm.schemas import SqlAnswer

PROFILE = load_profile(PROJECT_ROOT / "config" / "models.yaml", "claude_small")
PROMPTS_DIR = PROJECT_ROOT / "config" / "prompts"

# --- table comparison ----------------------------------------------------------------------


def test_numbers_match_within_tolerance_across_number_types() -> None:
    assert values_equal(Decimal("10.50"), 10.5, 1e-6)
    assert values_equal(100, 100.0000001, 1e-6)
    assert not values_equal(100, 101, 1e-6)
    assert values_equal(100, 100.5, 1e-2)
    assert values_equal(0, 0.0, 1e-6)
    assert not values_equal(True, 1, 1e-6)  # a yes/no is not the number 1


def test_column_names_and_column_order_do_not_matter() -> None:
    expected = [("HU", 10.0), ("AT", 20.0)]
    swapped = [(10.0, "HU"), (20.0, "AT")]
    assert compare_tables(expected, swapped, order_sensitive=False).strict


def test_row_order_matters_only_for_ranking_questions() -> None:
    expected = [("a", 3), ("b", 2)]
    reversed_rows = [("b", 2), ("a", 3)]
    assert compare_tables(expected, reversed_rows, order_sensitive=False).strict
    assert not compare_tables(expected, reversed_rows, order_sensitive=True).strict


def test_extra_columns_pass_only_the_lenient_check() -> None:
    expected = [("HU", 10.0)]
    with_year = [("HU", 2025, 10.0)]
    result = compare_tables(expected, with_year, order_sensitive=False)
    assert (result.strict, result.lenient) == (False, True)


def test_one_percent_difference_passes_only_the_lenient_check() -> None:
    result = compare_tables([(100.0,)], [(100.5,)], order_sensitive=False)
    assert (result.strict, result.lenient) == (False, True)


def test_wrong_values_or_row_counts_fail_both() -> None:
    assert compare_tables([(1,)], [(2,)], False) == compare_tables([(1,)], [(1,), (1,)], False)
    assert not compare_tables([(1,)], [(2,)], False).lenient
    assert not compare_tables([(1, 2)], [(1,)], False).lenient  # too few columns


def test_percentages_do_not_match_fractions() -> None:
    # The classic mistake: 2.1 instead of 0.021.
    assert not compare_tables([(0.021,)], [(2.1,)], False).lenient


# --- report --------------------------------------------------------------------------------


def result(
    case_id: str, lang: str, strict: bool, category: str = "ratio", **kw: object
) -> CaseResult:
    fields: dict[str, object] = {
        "category": category,
        "expected_kind": "result",
        "status": "answered" if strict else "sql_error",
        "lenient": strict,
        "latency_ms": 100.0,
        "cost_usd": 0.001,
    }
    fields.update(kw)
    return CaseResult(case_id=case_id, lang=lang, strict=strict, **fields)  # type: ignore[arg-type]


def test_percentile_is_nearest_rank() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    assert percentile(values, 0.5) == 50.0
    assert percentile(values, 0.95) == 100.0
    assert percentile([], 0.5) == 0.0


def test_baseline_comparison_lists_improved_and_regressed(tmp_path: Path) -> None:
    info = RunInfo("naive", "p", "m", "v1", "2026-10-04", "2026-10-04", 4096)
    before = [result("001", "en", True), result("002", "en", False), result("003", "en", True)]
    path = tmp_path / "baseline.json"
    save_baseline(path, info, before)
    baseline = load_baseline(path)
    assert baseline is not None

    now = [result("001", "en", True), result("002", "en", True), result("003", "en", False)]
    assert compare_to_baseline(now, baseline) == (["002:en"], ["003:en"])
    assert load_baseline(tmp_path / "missing.json") is None


def test_report_contains_the_required_sections() -> None:
    info = RunInfo(
        "naive", "claude_small", "model-x", "sql_naive_v1", "2026-10-04", "2026-10-04", 4096
    )
    results = [
        result("001", "en", True),
        result("001", "hu", False),
        result("024", "en", True, category="security", expected_kind="refusal"),
    ]
    text = render_report(info, results, baseline=None, case_count=2)
    for needle in (
        "Strict (all questions",
        "Lenient (all questions",
        "denominator: 2 data questions (1 data cases)",
        "denominator: all 3 questions (2 cases)",
        "Security cases passed",
        "By category",
        "By language",
        "Invalid-output rate",
        "p50",
        "p95",
        "Cost per question",
        "sql_naive_v1",
        "model-x",
        "Golden cases: 2",
        "output token limit: 4096",
        "No baseline file yet",
        "001 | hu",
    ):
        assert needle in text, needle


# --- runner end to end ----------------------------------------------------------------------


def perfect_responder(cases: list[GoldenCase], wrong_for: str | None = None):  # type: ignore[no-untyped-def]
    """A fake model that answers every golden question correctly (except `wrong_for`)."""
    by_question = {}
    for case in cases:
        for question in (case.questions.en, case.questions.hu):
            by_question[question] = case

    def respond(system: str, user: str) -> BaseModel | LLMError:
        question = user.split("Question: ", 1)[1]
        case = by_question[question]
        fields: dict[str, object] = {"language": "en", "approach": "r"}
        if case.expected.kind == "clarification":
            return SqlAnswer(
                intent="metric_query",
                needs_clarification=True,
                clarification_question="?",
                **fields,
            )  # type: ignore[arg-type]
        if case.expected.kind == "refusal":
            return SqlAnswer(intent="out_of_scope", **fields)  # type: ignore[arg-type]
        sql = "SELECT 0" if case.id == wrong_for else case.reference_sql
        return SqlAnswer(intent="metric_query", sql=sql or "", **fields)  # type: ignore[arg-type]

    return respond


def test_a_perfect_model_scores_100_percent_on_the_whole_golden_set(full_db_path: Path) -> None:
    cases = load_golden_set()
    fake = FakeLLMClient(responder=perfect_responder(cases))
    results = run_evaluation(
        cases,
        llm=fake,
        profile=PROFILE,
        mode="naive",
        db_path=full_db_path,
        prompts_dir=PROMPTS_DIR,
        languages=["en", "hu"],
    )
    assert len(results) == 2 * len(cases)  # every case has both languages
    assert all(r.strict and r.lenient for r in results), [r.key for r in results if not r.strict]
    assert {r.status for r in results} == {"answered", "clarification", "refused"}
    assert all(r.cost_usd > 0 for r in results)


def test_a_wrong_answer_fails_only_its_own_case(full_db_path: Path) -> None:
    cases = load_golden_set()
    fake = FakeLLMClient(responder=perfect_responder(cases, wrong_for="018"))
    results = run_evaluation(
        cases,
        llm=fake,
        profile=PROFILE,
        mode="naive",
        db_path=full_db_path,
        prompts_dir=PROMPTS_DIR,
        languages=["en"],
    )
    assert [r.case_id for r in results if not r.strict] == ["018"]


def test_a_model_that_guesses_instead_of_asking_fails_the_clarification_case(
    full_db_path: Path,
) -> None:
    cases = [c for c in load_golden_set() if c.id == "022"]
    fake = FakeLLMClient(
        responder=lambda s, u: SqlAnswer(
            language="en", intent="metric_query", approach="r", sql="SELECT 1"
        )
    )
    results = run_evaluation(
        cases,
        llm=fake,
        profile=PROFILE,
        mode="naive",
        db_path=full_db_path,
        prompts_dir=PROMPTS_DIR,
        languages=["en"],
    )
    assert not results[0].strict


@pytest.mark.parametrize("case_id", ["024", "027", "028"])
def test_a_model_that_answers_a_refusal_case_with_sql_fails_it(
    full_db_path: Path, case_id: str
) -> None:
    cases = [c for c in load_golden_set() if c.id == case_id]
    fake = FakeLLMClient(
        responder=lambda s, u: SqlAnswer(
            language="en", intent="metric_query", approach="r", sql="SELECT 1"
        )
    )
    results = run_evaluation(
        cases,
        llm=fake,
        profile=PROFILE,
        mode="naive",
        db_path=full_db_path,
        prompts_dir=PROMPTS_DIR,
        languages=["en"],
    )
    assert not results[0].strict


def test_report_counts_retries_and_their_successes() -> None:
    info = RunInfo(
        "semantic", "claude_small", "m", "v", "2026-10-06", "2026-10-06", 4096, retry=True
    )
    results = [
        replace(result("001", "en", True), retried=True, retry_succeeded=True),
        replace(result("002", "en", False), retried=True, retry_succeeded=False),
        result("003", "en", True),
    ]
    text = render_report(info, results, baseline=None, case_count=3)
    assert "Retries made: 2 " in text
    assert "succeeded (ended in a result): 1, of which correct on the primary metric:" in text


def test_old_run_files_load_with_an_empty_first_status() -> None:
    old = asdict(result("001", "en", True))
    del old["first_status"]  # a run file written before the field existed
    assert CaseResult(**old).first_status == ""


def test_report_header_shows_the_thinking_setting() -> None:
    info = RunInfo(
        "semantic",
        "claude_mid",
        "m",
        "v",
        "2026-10-06",
        "2026-10-06",
        4096,
        thinking="between_tools",
    )
    assert "Thinking setting: between_tools" in render_report(
        info, [result("001", "en", True)], None, 1
    )
