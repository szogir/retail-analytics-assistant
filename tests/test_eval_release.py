"""Regression tests for scoring, suite provenance and paired inference.

Normal tests exercise development data and synthetic examples. Sealed questions
are loaded only by the explicitly selected holdout/review release checks.
"""

import datetime as dt
import json
import os
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.compare import compare_tables, tables_match
from evals.golden import GOLDEN_SET_DIR, GoldenCase, load_golden_set
from evals.paired_analysis import paired_bootstrap
from evals.provenance import case_hash, file_hash, require_frozen, require_reviewed
from evals.report import CaseResult, RunInfo, load_baseline, save_baseline
from evals.run_eval import assumptions_match, grade, grade_primary
from evals.suites import suite_directory
from evals.validate_suite import check_ranking_tie, tie_probe_sql, verify_references
from retail_assistant.llm.schemas import SqlAnswer
from retail_assistant.pipeline import Answer
from retail_assistant.semantic.context import build_system_prompt
from retail_assistant.sql.executor import QueryResult


def test_tolerant_matching_can_reassign_an_earlier_match() -> None:
    # The first expected row can use either actual row, the second only the first.
    assert tables_match([(100.0,), (101.5,)], [(100.8,), (99.2,)], False, 0.01, False)
    assert tables_match([(101.5,), (100.0,)], [(100.8,), (99.2,)], False, 0.01, False)
    assert not tables_match([(100.0,), (100.0,)], [(100.0,), (200.0,)], False, 0.01, False)


def test_primary_allows_extra_columns_but_not_one_percent_numeric_error() -> None:
    assert compare_tables([(100.0,)], [(2025, 100.0)], False).primary
    result = compare_tables([(100.0,)], [(2025, 100.5)], False)
    assert result.lenient and not result.primary


@pytest.mark.parametrize("truncate_reference,truncate_answer", [(True, False), (False, True)])
def test_matching_prefixes_never_pass_when_truncated(
    truncate_reference: bool, truncate_answer: bool
) -> None:
    case = load_golden_set()[0]
    reference = QueryResult(["n"], [(10,)], truncate_reference)
    answer = Answer("answered", "q", result=QueryResult(["n"], [(10,)], truncate_answer))
    assert grade(case, answer, reference) == (False, False)
    assert not grade_primary(case, answer, reference)


def test_null_empty_and_zero_are_distinct_results() -> None:
    assert not compare_tables([(None,)], [(0,)], False).primary
    assert not compare_tables([], [(None,)], False).primary
    assert compare_tables([], [], False).primary


def test_answer_required_and_assumption_text_are_checked_separately() -> None:
    case = next(c for c in load_golden_set() if c.id == "029")
    result = QueryResult(["n"], [(123,)], False)
    answer = Answer("clarification", "q", message="Which revenue?")
    assert not grade_primary(case, answer, result)
    model = SqlAnswer(
        language="hu", intent="metric_query", approach="Calculation", sql="SELECT 123"
    )
    answered = Answer("answered", "q", result=result, model_answer=model)
    assert grade_primary(case, answered, result)
    assert not assumptions_match(case, answered, "hu")
    model.assumptions = ["A bevételt nettó árbevételként értelmezem."]
    assert assumptions_match(case, answered, "hu")


def test_review_metadata_cannot_claim_approval_without_a_person_and_date() -> None:
    # Start from a pending case: the frozen suite on disk is already approved, so its
    # dump would carry a reviewer and date and the claim below would be valid.
    payload = load_golden_set()[0].model_dump()
    payload.update(reviewed=True, reviewed_on=None, reviewed_by=None)
    with pytest.raises(ValidationError):
        GoldenCase.model_validate(payload)
    payload.update(reviewed_by="Owner", reviewed_on=dt.date(2026, 10, 4))
    reviewed = GoldenCase.model_validate(payload)
    require_reviewed([reviewed])
    pending = reviewed.model_copy(
        update={"reviewed": False, "reviewed_on": None, "reviewed_by": None}
    )
    with pytest.raises(ValueError, match="Human review required"):
        require_reviewed([pending])


def test_case_hash_covers_text_sql_and_reviews_but_not_file_order() -> None:
    cases = load_golden_set()
    assert case_hash(cases) == case_hash(list(reversed(cases)))
    changed = cases[0].model_copy(update={"reference_sql": "SELECT 0"})
    assert case_hash(cases) != case_hash([changed, *cases[1:]])
    changed = cases[0].model_copy(update={"notes": "Changed business interpretation"})
    assert case_hash(cases) != case_hash([changed, *cases[1:]])


def test_baseline_with_another_suite_version_is_rejected(tmp_path: Path) -> None:
    info = RunInfo(
        "naive",
        "p",
        "m",
        "v",
        "2026-10-04",
        "2026-10-04",
        4096,
        suite="development",
        case_hash="one",
    )
    path = tmp_path / "baseline.json"
    save_baseline(path, info, [])
    with pytest.raises(ValueError, match="case_hash"):
        load_baseline(path, replace(info, case_hash="two"))


def test_frozen_release_rejects_changed_files_and_candidate_manifests(tmp_path: Path) -> None:
    case = load_golden_set()[0].model_copy(
        update={"reviewed": True, "reviewed_on": dt.date(2026, 10, 4), "reviewed_by": "Owner"}
    )
    db = tmp_path / "database.bin"
    db.write_bytes(b"fixed database content")
    oracle = tmp_path / "oracles.py"
    oracle.write_text("# Independent calculation placeholder for this unit test\n")
    case_file = tmp_path / "001.yaml"
    case_file.write_text("case content\n")
    manifest = {
        "status": "frozen",
        "reference_cases_checked": [case.id],
        "case_hash": case_hash([case]),
        "case_count": 1,
        "database_hash": file_hash(db),
        "files": {case_file.name: file_hash(case_file)},
        "oracle_hash": file_hash(oracle),
        "reference_tools_hash": file_hash(GOLDEN_SET_DIR.parent / "reference_tools.py"),
    }
    path = tmp_path / "frozen.json"
    path.write_text(json.dumps(manifest))
    require_frozen(tmp_path, [case], db)
    case_file.write_text("modified SQL or question\n")
    with pytest.raises(ValueError, match="YAML"):
        require_frozen(tmp_path, [case], db)
    manifest["status"] = "candidate_pending_human_review"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="candidate manifest"):
        require_frozen(tmp_path, [case], db)


def observations(passed: bool) -> list[CaseResult]:
    """Two synthetic cases, retaining their six repeated bilingual observations."""
    return [
        CaseResult(
            case_id,
            lang,
            "aggregation",
            "result",
            "answered",
            passed,
            passed,
            1.0,
            0.0,
            primary=passed,
            repeat=repeat,
        )
        for case_id in ("a", "b")
        for lang in ("en", "hu")
        for repeat in (1, 2, 3)
    ]


def test_bootstrap_keeps_languages_and_repeats_inside_the_case() -> None:
    estimate = paired_bootstrap(observations(False), observations(True), samples=100)
    assert estimate.cases == 2  # not twelve independent questions
    assert estimate.difference == estimate.lower == estimate.upper == 1
    assert estimate.meets_success_rule
    zero = paired_bootstrap(observations(True), observations(True), samples=100)
    assert zero.difference == zero.lower == zero.upper == 0
    assert not zero.meets_success_rule


def test_estimate_contains_only_plain_python_values() -> None:
    # Regression: NumPy 2 scalars (`np.bool_`, `np.float64`) are not JSON serializable,
    # and the analysis CLI prints this estimate as JSON.
    estimate = paired_bootstrap(observations(False), observations(True), samples=100)
    assert all(type(value) in (int, float, bool) for value in asdict(estimate).values())
    json.dumps(asdict(estimate))


def test_bootstrap_rejects_missing_and_duplicate_pairs() -> None:
    with pytest.raises(ValueError, match="identical, unique"):
        paired_bootstrap(observations(True), observations(True)[:-1])
    short = observations(True)[:-1]
    with pytest.raises(ValueError, match="both languages"):
        paired_bootstrap(short, short)
    duplicate = [*observations(True), observations(True)[0]]
    with pytest.raises(ValueError, match="identical, unique"):
        paired_bootstrap(duplicate, duplicate)


def test_development_has_the_agreed_composition() -> None:
    cases = load_golden_set()
    assert len(cases) == 50
    assert sum(c.expected.kind == "result" for c in cases) == 40
    assert sum(c.expected.kind == "clarification" for c in cases) == 5
    assert sum(c.category == "security" for c in cases) == 4
    assert sum("default_assumption" in c.tags for c in cases) == 15


def test_commented_mode_adds_real_metadata_without_metric_definitions(full_db_path: Path) -> None:
    prompts = GOLDEN_SET_DIR.parent.parent / "config" / "prompts"
    naive = build_system_prompt("naive", full_db_path, prompts)
    commented = build_system_prompt("commented", full_db_path, prompts)
    assert "DIVIDE" not in naive and "DIVIDE" in commented
    assert "gross - discount - VAT" not in commented
    assert naive.split("## How to answer")[1] == commented.split("## How to answer")[1]


def test_every_development_reference_has_independent_arithmetic(
    full_db_path: Path, tmp_path: Path
) -> None:
    # Work on a copy so a unit test never overwrites the owner's review artifacts.
    import shutil

    for path in GOLDEN_SET_DIR.iterdir():
        if path.suffix in (".py", ".yaml"):
            shutil.copyfile(path, tmp_path / path.name)
    manifest = verify_references(tmp_path, full_db_path)
    assert len(manifest["reference_cases_checked"]) == 40


def _ranking_case(sql: str) -> GoldenCase:
    base = load_golden_set()[0]
    return base.model_copy(update={"reference_sql": sql})


def _tie_db(tmp_path: Path, values: list[tuple[str, float]]) -> Path:
    import duckdb

    path = tmp_path / "ties.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute("CREATE TABLE t (name VARCHAR, v DOUBLE)")
        connection.executemany("INSERT INTO t VALUES (?, ?)", values)
    return path


@pytest.mark.parametrize(
    "order_by",
    ["SUM(v) DESC", "total DESC", "2 DESC"],
)
def test_ranking_guard_rejects_a_tie_at_the_cutoff(tmp_path: Path, order_by: str) -> None:
    # Cutoff is between the 1st and 2nd row: both have the same total.
    db_path = _tie_db(tmp_path, [("a", 5.0), ("b", 5.0), ("c", 1.0)])
    sql = f"SELECT name, SUM(v) AS total FROM t GROUP BY name ORDER BY {order_by} LIMIT 1"  # noqa: S608
    with pytest.raises(ValueError, match="Ranking tie"):
        check_ranking_tie(_ranking_case(sql), db_path)


def test_ranking_guard_accepts_a_clear_cutoff_and_ignores_other_queries(tmp_path: Path) -> None:
    db_path = _tie_db(tmp_path, [("a", 5.0), ("b", 4.0), ("c", 4.0)])
    top_one = "SELECT name FROM t ORDER BY v DESC LIMIT 1"
    check_ranking_tie(_ranking_case(top_one), db_path)
    # A tie below the cutoff (b and c) does not matter for the top 1.
    assert tie_probe_sql("SELECT name FROM t ORDER BY v DESC") is None
    assert tie_probe_sql("SELECT name FROM t LIMIT 3") is None
    with pytest.raises(ValueError, match="Ranking tie"):
        check_ranking_tie(_ranking_case("SELECT name, v FROM t ORDER BY v DESC LIMIT 2"), db_path)


def test_growth_without_a_base_is_none_not_an_error() -> None:
    from evals.golden_set.oracles import growth

    assert growth(110.0, 100.0) == pytest.approx(0.1)
    assert growth(110.0, 0) is None
    assert growth(110.0, None) is None
    assert growth(None, 100.0) is None


@pytest.mark.holdout
def test_sealed_references_and_composition(full_db_path: Path, tmp_path: Path) -> None:
    import shutil

    if not os.environ.get("HOLDOUT_DIR"):
        pytest.skip("External holdout not configured: set HOLDOUT_DIR to run this check locally")
    directory = suite_directory("holdout")
    # Keep every copy and review output inside the sealed boundary.
    target = directory / "artifacts" / "test-suite"
    target.mkdir(parents=True, exist_ok=True)
    cases = load_golden_set(directory)
    assert len(cases) == 50
    assert sum(c.expected.kind == "result" for c in cases) == 38
    assert sum(c.expected.kind == "clarification" for c in cases) == 7
    assert sum(c.category == "security" for c in cases) == 4
    assert sum("default_assumption" in c.tags for c in cases) == 27
    assert not {q for c in cases for q in (c.questions.en, c.questions.hu)} & {
        q for c in load_golden_set() for q in (c.questions.en, c.questions.hu)
    }
    for path in directory.iterdir():
        if path.suffix in (".py", ".yaml"):
            shutil.copyfile(path, target / path.name)
    manifest = verify_references(target, full_db_path)
    assert len(manifest["reference_cases_checked"]) == 38


@pytest.mark.review
def test_all_development_cases_have_personal_approval() -> None:
    cases = load_golden_set()
    if any(not case.reviewed for case in cases):
        pytest.xfail("Personal approval is pending; the freeze command still rejects this suite")
    require_reviewed(cases)


@pytest.mark.review
@pytest.mark.holdout
def test_all_holdout_cases_have_personal_approval() -> None:
    if not os.environ.get("HOLDOUT_DIR"):
        pytest.skip("External holdout not configured: set HOLDOUT_DIR to run this check locally")
    cases = load_golden_set(suite_directory("holdout"))
    if any(not case.reviewed for case in cases):
        pytest.xfail("Personal approval is pending; the freeze command still rejects this suite")
    require_reviewed(cases)


@pytest.mark.parametrize("recorded_count", [2, 3])
def test_confirmatory_analysis_requires_all_recorded_data_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_count: int
) -> None:
    from evals.paired_analysis import main

    info = {
        "suite": "holdout",
        "holdout_verified": True,
        "holdout_manifest_hash": "synthetic-manifest",
        "data_case_count": recorded_count,
    }
    paths = []
    for mode in ("commented", "semantic"):
        path = tmp_path / f"{mode}.json"
        path.write_text(
            json.dumps(
                {
                    "info": {**info, "mode": mode},
                    "results": [asdict(row) for row in observations(mode == "semantic")],
                }
            ),
            encoding="utf-8",
        )
        paths.append(str(path))
    monkeypatch.setattr("sys.argv", ["paired_analysis", *paths])
    if recorded_count == 2:
        main()
    else:
        with pytest.raises(ValueError, match="every recorded data case"):
            main()


def _frozen_fixture(tmp_path: Path, case_bytes: bytes) -> tuple[Path, GoldenCase, Path]:
    """A frozen manifest recorded from `case_bytes`, written the way the freeze did."""
    case = load_golden_set()[0].model_copy(
        update={"reviewed": True, "reviewed_on": dt.date(2026, 10, 4), "reviewed_by": "Owner"}
    )
    db = tmp_path / "database.bin"
    db.write_bytes(b"fixed database content")
    oracle = tmp_path / "oracles.py"
    oracle.write_bytes(b"# placeholder\n")
    case_file = tmp_path / "001.yaml"
    case_file.write_bytes(case_bytes)
    manifest = {
        "status": "frozen",
        "reference_cases_checked": [case.id],
        "case_hash": case_hash([case]),
        "case_count": 1,
        "database_hash": file_hash(db),
        "files": {case_file.name: file_hash(case_file)},
        "oracle_hash": file_hash(oracle),
        "reference_tools_hash": file_hash(GOLDEN_SET_DIR.parent / "reference_tools.py"),
    }
    (tmp_path / "frozen.json").write_text(json.dumps(manifest))
    return db, case, case_file


CRLF_CASE = b"id: 1\r\nquestion: net sales\r\n"


def test_crlf_frozen_file_passes_in_an_lf_checkout(tmp_path: Path) -> None:
    db, case, case_file = _frozen_fixture(tmp_path, CRLF_CASE)
    assert require_frozen(tmp_path, [case], db) == []  # untouched bytes: plain match
    case_file.write_bytes(CRLF_CASE.replace(b"\r\n", b"\n"))  # what git checks out
    assert require_frozen(tmp_path, [case], db) == ["001.yaml"]  # passes, and says so


def test_one_changed_content_byte_fails_even_with_lf_endings(tmp_path: Path) -> None:
    db, case, case_file = _frozen_fixture(tmp_path, CRLF_CASE)
    case_file.write_bytes(b"id: 1\nquestion: net sales!\n")
    with pytest.raises(ValueError, match="YAML"):
        require_frozen(tmp_path, [case], db)


def test_mixed_line_endings_that_differ_after_normalization_fail(tmp_path: Path) -> None:
    db, case, case_file = _frozen_fixture(tmp_path, CRLF_CASE)
    case_file.write_bytes(b"id: 1\r\nquestion: net sales\n\n")  # extra blank line
    with pytest.raises(ValueError, match="YAML"):
        require_frozen(tmp_path, [case], db)
