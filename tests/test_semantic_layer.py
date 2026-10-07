"""Tests for the semantic layer: files, traceability, executable SQL and the prompt.

Everything runs offline against the generated database, opened read-only. Nothing here
writes to the database (its hash is part of the holdout commitment).
"""

import copy
import datetime as dt
import json
import re
import shutil
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import duckdb
import pytest
import yaml

from evals.golden import load_golden_set
from evals.report import (
    CaseResult,
    RunInfo,
    baseline_from_run_file,
    render_report,
)
from evals.suites import suite_directory
from retail_assistant.config import PROJECT_ROOT
from retail_assistant.llm.fake import FakeLLMClient
from retail_assistant.llm.profiles import load_profile
from retail_assistant.llm.schemas import SqlAnswer
from retail_assistant.pipeline import ask
from retail_assistant.semantic.context import (
    build_system_prompt,
    prompt_version,
    render_semantic_section,
)
from retail_assistant.semantic.loader import (
    FILE_NAMES,
    SemanticLayerError,
    check_sources,
    load_semantic_layer,
)
from retail_assistant.semantic.models import Metric, SemanticLayer

SEMANTIC_DIR = PROJECT_ROOT / "semantic"
DOCS_DIR = PROJECT_ROOT / "docs"
PROMPTS_DIR = PROJECT_ROOT / "config" / "prompts"
PROFILE = load_profile(PROJECT_ROOT / "config" / "models.yaml", "claude_small")


@pytest.fixture(scope="module")
def layer() -> SemanticLayer:
    return load_semantic_layer(SEMANTIC_DIR)


def copy_semantic(tmp_path: Path) -> Path:
    """Copy the real semantic files so a test can break one of them."""
    target = tmp_path / "semantic"
    shutil.copytree(SEMANTIC_DIR, target)
    return target


def edit_yaml(directory: Path, name: str, change: Callable[[Any], object]) -> None:
    """Load a YAML file, apply `change(document)` and write it back."""
    path = directory / name
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")


def normalise(text: str) -> str:
    """Lower-case and collapse whitespace, so formatting differences do not hide an overlap."""
    return re.sub(r"\s+", " ", text.lower()).strip()


# --- files, versions and traceability ---------------------------------------------------


def test_all_four_files_load_with_a_version_and_a_hash(layer: SemanticLayer) -> None:
    assert set(layer.file_hashes) == set(FILE_NAMES)
    assert all(len(digest) == 64 for digest in layer.file_hashes.values())
    assert all(version >= 1 for version in layer.file_versions.values())


def test_every_entry_has_a_source_that_exists(layer: SemanticLayer, full_db_path: Path) -> None:
    assert check_sources(layer, DOCS_DIR, full_db_path) == []


def test_a_source_that_does_not_exist_is_reported(tmp_path: Path, full_db_path: Path) -> None:
    directory = copy_semantic(tmp_path)
    edit_yaml(
        directory,
        "rules.yaml",
        lambda doc: doc["rules"][0].update(source="contract:No such section"),
    )
    edit_yaml(directory, "metrics.yaml", lambda doc: doc["metrics"][0].update(source="decision:99"))
    edit_yaml(
        directory,
        "joins.yaml",
        lambda doc: doc["joins"][0].update(source="schema:dim_store.no_such_column"),
    )
    problems = check_sources(load_semantic_layer(directory), DOCS_DIR, full_db_path)
    assert any("dim_store.no_such_column" in problem for problem in problems)
    assert any("No such section" in problem for problem in problems)
    assert any("decision 99" in problem for problem in problems)


def test_a_source_must_be_spelled_correctly(tmp_path: Path) -> None:
    directory = copy_semantic(tmp_path)
    edit_yaml(directory, "rules.yaml", lambda doc: doc["rules"][0].update(source="somewhere"))
    with pytest.raises(SemanticLayerError, match="source must look like"):
        load_semantic_layer(directory)


def test_join_sources_name_the_key_column_they_rely_on(layer: SemanticLayer) -> None:
    sources = {j.name: j.source for j in layer.joins.joins}
    assert sources["store"] == "schema:dim_store.store_id"
    assert sources["product"] == "schema:dim_product.product_id"
    assert sources["date"] == "schema:dim_date.date"


def test_a_missing_source_is_rejected(tmp_path: Path) -> None:
    directory = copy_semantic(tmp_path)
    edit_yaml(directory, "joins.yaml", lambda doc: doc["joins"][0].pop("source"))
    with pytest.raises(SemanticLayerError, match="joins.yaml"):
        load_semantic_layer(directory)


def test_editing_a_file_changes_its_hash(tmp_path: Path) -> None:
    directory = copy_semantic(tmp_path)
    before = load_semantic_layer(directory).file_hashes
    with (directory / "rules.yaml").open("a", encoding="utf-8") as handle:
        handle.write("\n# a comment is enough to change the fingerprint\n")
    after = load_semantic_layer(directory).file_hashes
    assert after["rules.yaml"] != before["rules.yaml"]
    assert after["metrics.yaml"] == before["metrics.yaml"]


# --- validation errors --------------------------------------------------------------------


def test_missing_file_names_the_file(tmp_path: Path) -> None:
    directory = copy_semantic(tmp_path)
    (directory / "joins.yaml").unlink()
    with pytest.raises(SemanticLayerError, match="joins.yaml"):
        load_semantic_layer(directory)


def test_unknown_keys_are_errors_not_ignored(tmp_path: Path) -> None:
    directory = copy_semantic(tmp_path)
    edit_yaml(directory, "metrics.yaml", lambda doc: doc["metrics"][0].update(synonym=["x"]))
    with pytest.raises(SemanticLayerError, match="metrics.yaml"):
        load_semantic_layer(directory)


def test_duplicate_metric_names_are_rejected(tmp_path: Path) -> None:
    directory = copy_semantic(tmp_path)
    edit_yaml(
        directory,
        "metrics.yaml",
        lambda doc: doc["metrics"].append(copy.deepcopy(doc["metrics"][0])),
    )
    with pytest.raises(SemanticLayerError, match="duplicate metric names"):
        load_semantic_layer(directory)


def test_a_metric_needing_an_unknown_join_is_rejected(tmp_path: Path) -> None:
    directory = copy_semantic(tmp_path)
    edit_yaml(directory, "metrics.yaml", lambda doc: doc["metrics"][0].update(requires=["nope"]))
    with pytest.raises(SemanticLayerError, match="unknown join"):
        load_semantic_layer(directory)


def test_an_example_pointing_at_an_unknown_rule_is_rejected(tmp_path: Path) -> None:
    directory = copy_semantic(tmp_path)
    edit_yaml(
        directory, "examples.yaml", lambda doc: doc["examples"][0].update(demonstrates=["nope"])
    )
    with pytest.raises(SemanticLayerError, match="unknown nope"):
        load_semantic_layer(directory)


def test_a_ratio_needs_numerator_and_denominator(tmp_path: Path) -> None:
    directory = copy_semantic(tmp_path)

    def break_ratio(doc: dict[str, list[dict[str, object]]]) -> None:
        basket = next(m for m in doc["metrics"] if m["name"] == "avg_basket_eur")
        basket["expression"] = "AVG(f.gross_amount)"

    edit_yaml(directory, "metrics.yaml", break_ratio)
    with pytest.raises(SemanticLayerError, match="numerator and denominator"):
        load_semantic_layer(directory)


def test_a_ratio_divides_by_a_nullif_denominator(layer: SemanticLayer) -> None:
    basket = next(m for m in layer.metrics.metrics if m.name == "avg_basket_eur")
    assert basket.sql_expression.endswith("/ NULLIF(COUNT(DISTINCT f.receipt_id), 0)")


# --- content the business contract requires -----------------------------------------------


def metric(layer: SemanticLayer, name: str) -> Metric:
    return next(m for m in layer.metrics.metrics if m.name == name)


def test_net_sales_says_returns_reduce_the_total_and_are_not_filtered(
    layer: SemanticLayer,
) -> None:
    net_sales = metric(layer, "net_sales_eur")
    assert "Returns are negative lines" in net_sales.description
    assert "reduce net sales" in net_sales.description
    assert "NOT filtered out" in net_sales.description
    assert not any("is_return" in f for f in net_sales.mandatory_filters)
    assert "is_return" not in net_sales.sql_expression


def test_the_requested_metrics_exist(layer: SemanticLayer) -> None:
    names = {m.name for m in layer.metrics.metrics}
    assert {
        "net_sales_eur",
        "gross_sales_eur",
        "units_sold",
        "receipt_count",
        "avg_basket_eur",
        "return_rate",
        "discount_rate",
        "private_label_share",
        "net_sales_local",
        "trading_days",
        "avg_daily_net_sales_eur",
    } <= names


def test_local_currency_net_sales_has_no_exchange_rate(layer: SemanticLayer) -> None:
    local = metric(layer, "net_sales_local")
    assert "eur_rate" not in local.sql_expression
    assert "fx" not in local.requires


def test_every_euro_metric_divides_by_the_rate(layer: SemanticLayer) -> None:
    for item in layer.metrics.metrics:
        if "fx" in item.requires:
            assert "/ fx.eur_rate" in item.sql_expression, item.name
            assert "* fx.eur_rate" not in item.sql_expression, item.name


def test_every_metric_excludes_cancelled_receipts_and_test_stores(layer: SemanticLayer) -> None:
    for item in layer.metrics.metrics:
        assert "NOT f.is_cancelled" in item.mandatory_filters, item.name
        assert "NOT s.is_test_store" in item.mandatory_filters, item.name


def test_the_required_rules_exist(layer: SemanticLayer) -> None:
    rules = {r.name: r for r in layer.rules.rules}
    assert "DIVIDING" in rules["fx_rate_direction"].statement
    assert "units of the currency per 1 EUR" in rules["fx_rate_direction"].statement
    assert "trading date" in rules["average_per_day"].statement
    assert rules["average_per_day"].source == "decision:7"
    assert "last available day before today" in rules["as_of_date_and_coverage"].statement
    relative = rules["relative_periods"].statement
    assert "previous full calendar month" in relative
    assert "September 2026" in relative and "July-September 2026" in relative
    assert layer.rules.version >= 3
    assert any(j.name == "store_holiday" for j in layer.joins.joins)


def test_cancellation_subject_keeps_returns_and_test_stores_out(layer: SemanticLayer) -> None:
    rule = {r.name: r for r in layer.rules.rules}["cancellation_as_subject"].statement
    assert "NOT f.is_return" in rule and "test stores" in rule


def test_milk_means_both_brand_labels_and_not_a_language_label(layer: SemanticLayer) -> None:
    rule = {r.name: r for r in layer.rules.rules}["product_selection"]
    assert "House Label" in rule.statement
    assert "name_en LIKE 'Whole milk 1 l (%'" in rule.statement
    assert "language label" not in rule.statement
    assert rule.source == "contract:Measures + schema:dim_product.name_en"


def test_milk_patterns_select_exactly_the_four_milk_products(
    db: duckdb.DuckDBPyConnection,
) -> None:
    names = db.execute(
        "SELECT name_en FROM dim_product WHERE name_en LIKE 'Whole milk 1 l (%' "
        "OR name_en LIKE 'Semi-skimmed milk 1 l (%'"
    ).fetchall()
    assert len(names) == 4


def test_master_data_questions_are_metric_queries(layer: SemanticLayer) -> None:
    rule = {r.name: r for r in layer.rules.rules}["master_data_questions"].statement
    assert "metric_query" in rule and "NOT is_test_store" in rule


# --- everything that is SQL actually runs -------------------------------------------------


def test_every_join_path_runs(db: duckdb.DuckDBPyConnection, layer: SemanticLayer) -> None:
    for join in layer.joins.joins:
        left = f"{join.left_table} {join.left_alias}"
        right = f"{join.right_table} {join.right_alias}"
        sql = f"SELECT 1 FROM {left} JOIN {right} ON {join.condition} LIMIT 1"  # noqa: S608
        assert db.execute(sql).fetchall(), join.name


def test_every_metric_runs_with_its_joins_and_filters(
    db: duckdb.DuckDBPyConnection, layer: SemanticLayer
) -> None:
    joins = {j.name: j for j in layer.joins.joins}
    for item in layer.metrics.metrics:
        join_sql = " ".join(
            f"JOIN {joins[n].right_table} {joins[n].right_alias} ON {joins[n].condition}"
            for n in item.requires
        )
        where = " AND ".join(item.mandatory_filters)
        base = f"{item.base_table} {layer.joins.base_alias}"
        sql = f"SELECT {item.sql_expression} FROM {base} {join_sql} WHERE {where}"  # noqa: S608
        (value,) = db.execute(sql).fetchone() or (None,)
        assert value is not None, item.name


def test_every_example_runs_and_returns_rows(
    db: duckdb.DuckDBPyConnection, layer: SemanticLayer
) -> None:
    for example in layer.examples.examples:
        assert db.execute(example.sql).fetchall(), example.id


# --- examples come from the contract, not from the development cases ----------------------


def test_examples_cover_the_hardest_rules(layer: SemanticLayer) -> None:
    shown = {name for e in layer.examples.examples for name in e.demonstrates}
    assert {
        "net_sales_definition",
        "ratios_from_sums",
        "calendar_vs_fiscal",
        "fx_rate_direction",
        "net_sales_local",
    } <= shown
    assert len(layer.examples.examples) == 5


def test_examples_do_not_overlap_with_the_development_suite(layer: SemanticLayer) -> None:
    cases = load_golden_set(suite_directory("development"))
    questions = {normalise(c.questions.en) for c in cases}
    statements = {normalise(c.reference_sql) for c in cases if c.reference_sql}
    for example in layer.examples.examples:
        assert normalise(example.question) not in questions, example.id
        assert normalise(example.sql) not in statements, example.id
        # A near-copy of a question (same words, one number changed) is also an overlap.
        words = set(normalise(example.question).split())
        for question in questions:
            other = set(question.split())
            assert len(words & other) / len(words | other) < 0.75, (example.id, question)


# --- the prompt ---------------------------------------------------------------------------


def test_semantic_prompt_contains_every_definition(
    full_db_path: Path, layer: SemanticLayer
) -> None:
    prompt = build_system_prompt("semantic", full_db_path, PROMPTS_DIR, SEMANTIC_DIR)
    for item in layer.metrics.metrics:
        assert item.name in prompt and item.sql_expression in prompt
    for rule in layer.rules.rules:
        assert rule.statement in prompt
    for join in layer.joins.joins:
        assert join.condition in prompt
    for example in layer.examples.examples:
        assert example.question in prompt
    assert "{schema}" not in prompt and "{semantic}" not in prompt
    # Semantic = commented + layer, so the column comments must still be there.
    assert "DIVIDE it by this rate" in prompt
    assert prompt_version("semantic") == "sql_semantic_v1"


def test_semantic_section_is_deterministic_and_prompts_stay_separate(
    full_db_path: Path, layer: SemanticLayer
) -> None:
    assert render_semantic_section(layer) == render_semantic_section(layer)
    naive = build_system_prompt("naive", full_db_path, PROMPTS_DIR)
    commented = build_system_prompt("commented", full_db_path, PROMPTS_DIR)
    assert "net_sales_eur" not in naive and "net_sales_eur" not in commented


def test_semantic_mode_needs_the_semantic_folder(full_db_path: Path) -> None:
    with pytest.raises(ValueError, match="semantic"):
        build_system_prompt("semantic", full_db_path, PROMPTS_DIR)


def test_the_pipeline_sends_the_semantic_prompt(tiny_db: Path) -> None:
    fake = FakeLLMClient(
        responses=[
            SqlAnswer.model_validate(
                {
                    "language": "en",
                    "intent": "metric_query",
                    "approach": "count",
                    "sql": "SELECT COUNT(*) FROM dim_store",
                }
            )
        ]
    )
    result = ask(
        "How many stores?",
        "carla",
        "en",
        "semantic",
        llm=fake,
        profile=PROFILE,
        db_path=tiny_db,
        prompts_dir=PROMPTS_DIR,
        as_of=dt.date(2026, 10, 4),
        semantic_dir=SEMANTIC_DIR,
        validate=False,
    )
    assert result.status == "answered"
    assert result.prompt_version == "sql_semantic_v1"
    assert "net_sales_eur" in fake.calls[0].system


# --- report header, comparison with an earlier run, diagnostic analysis -----------------------


def run_info(**changes: object) -> RunInfo:
    base = RunInfo(
        mode="semantic",
        profile="claude_small",
        model="m",
        prompt_version="sql_semantic_v1",
        price_date="2026-10-04",
        run_date="2026-10-05",
        max_tokens=4096,
        suite="development",
    )
    return RunInfo(**{**asdict(base), **changes})


def result(case_id: str, lang: str, repeat: int, primary: bool) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        lang=lang,
        category="ratio",
        expected_kind="result",
        status="answered",
        strict=primary,
        lenient=primary,
        latency_ms=1.0,
        cost_usd=0.0,
        primary=primary,
        repeat=repeat,
    )


def test_report_header_lists_each_semantic_file_with_version_and_hash(
    layer: SemanticLayer,
) -> None:
    info = run_info(semantic_files=layer.file_hashes, semantic_versions=layer.file_versions)
    report = render_report(info, [result("001", "en", 1, True)], None, 1)
    for name, digest in layer.file_hashes.items():
        assert f"`{name}` v{layer.file_versions[name]} SHA-256: `{digest}`" in report
    plain = render_report(run_info(), [result("001", "en", 1, True)], None, 1)
    assert "Semantic file" not in plain


def test_improved_and_regressed_are_listed_against_an_earlier_run(tmp_path: Path) -> None:
    info = run_info()
    earlier = [result("001", "en", 1, False), result("002", "en", 1, True)]
    dump = tmp_path / "commented.json"
    dump.write_text(
        json.dumps(
            {"info": asdict(run_info(mode="commented")), "results": [asdict(r) for r in earlier]}
        ),
        encoding="utf-8",
    )
    now = [result("001", "en", 1, True), result("002", "en", 1, False)]
    report = render_report(info, now, baseline_from_run_file(dump, info), 2, "earlier run x")
    assert "## Versus earlier run x" in report
    assert "Primary improved (1): 001:en" in report
    assert "Primary regressed (1): 002:en" in report


def test_an_earlier_run_with_other_settings_is_not_comparable(tmp_path: Path) -> None:
    dump = tmp_path / "other.json"
    dump.write_text(
        json.dumps({"info": asdict(run_info(model="another")), "results": []}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="model"):
        baseline_from_run_file(dump, run_info())


def write_dump(path: Path, mode: str, suite: str, wins: set[str]) -> None:
    results = [
        asdict(result(case, lang, repeat, case in wins))
        for case in ("001", "002", "003")
        for lang in ("en", "hu")
        for repeat in (1, 2, 3)
    ]
    info = asdict(run_info(mode=mode, suite=suite, data_case_count=3, repetitions=3))
    path.write_text(json.dumps({"info": info, "results": results}), encoding="utf-8")


def test_paired_analysis_of_the_development_suite_is_labelled_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from evals.paired_analysis import main

    write_dump(tmp_path / "a.json", "commented", "development", {"001"})
    write_dump(tmp_path / "b.json", "semantic", "development", {"001", "002", "003"})
    monkeypatch.setattr(
        sys, "argv", ["x", str(tmp_path / "a.json"), str(tmp_path / "b.json"), "--diagnostic"]
    )
    main()
    output = json.loads(capsys.readouterr().out)
    assert output["confirmatory"] is False
    assert output["label"].startswith("DIAGNOSTIC")
    assert "meets_success_rule" not in output
    assert output["comparison"] == "semantic minus commented"


def test_paired_analysis_of_the_development_suite_needs_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evals.paired_analysis import main

    write_dump(tmp_path / "a.json", "commented", "development", {"001"})
    write_dump(tmp_path / "b.json", "semantic", "development", {"001", "002"})
    monkeypatch.setattr(sys, "argv", ["x", str(tmp_path / "a.json"), str(tmp_path / "b.json")])
    with pytest.raises(ValueError, match="holdout"):
        main()


def test_the_diagnostic_flag_is_refused_for_other_suites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evals.paired_analysis import main

    write_dump(tmp_path / "a.json", "commented", "holdout", {"001"})
    write_dump(tmp_path / "b.json", "semantic", "holdout", {"001", "002"})
    monkeypatch.setattr(
        sys, "argv", ["x", str(tmp_path / "a.json"), str(tmp_path / "b.json"), "--diagnostic"]
    )
    with pytest.raises(ValueError, match="only for runs of the development suite"):
        main()
