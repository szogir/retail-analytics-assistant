"""Tests for the CLI and the presentation (fake model, no network).

The fake client replaces the model; the database is the real generated one, so the user
scoping (anna vs carla) is the real access layer.
"""

import datetime as dt
from pathlib import Path

import pytest
from typer.testing import CliRunner

from retail_assistant import cli
from retail_assistant.config import PROJECT_ROOT
from retail_assistant.llm.factory import LLMSetup
from retail_assistant.llm.fake import FakeLLMClient
from retail_assistant.llm.profiles import ModelProfile
from retail_assistant.llm.schemas import SqlAnswer
from retail_assistant.presentation import format_value, resolve_metrics
from retail_assistant.semantic.loader import load_semantic_layer

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
# Fixed prices, so that the printed cost does not change when config/models.yaml is updated.
TEST_PROFILE = ModelProfile(
    name="test",
    provider="anthropic",
    model="test-model",
    price_date=dt.date(2026, 10, 6),
    input_per_mtok=1.0,
    cached_input_per_mtok=0.1,
    cache_write_per_mtok=1.25,
    output_per_mtok=5.0,
)
runner = CliRunner()


def answer(**fields: object) -> SqlAnswer:
    base: dict[str, object] = {"language": "en", "intent": "metric_query", "approach": "plan"}
    return SqlAnswer.model_validate({**base, **fields})


@pytest.fixture
def use_fake(monkeypatch: pytest.MonkeyPatch, full_db_path: Path):  # type: ignore[no-untyped-def]
    """Point the CLI at the generated database and a scripted fake model."""
    monkeypatch.setenv("RETAIL_DB_PATH", str(full_db_path))
    monkeypatch.setenv("COLUMNS", "100")  # rich wraps at this width, so output is stable

    def install(*responses: SqlAnswer) -> FakeLLMClient:
        fake = FakeLLMClient(responses=list(responses))
        monkeypatch.setattr(
            cli, "build_llm", lambda settings, profile: LLMSetup(fake, TEST_PROFILE)
        )
        return fake

    return install


def ask_cli(*args: str) -> str:
    result = runner.invoke(cli.app, ["ask", *args])
    assert result.exit_code == 0, result.output
    return result.output


def test_ask_output_matches_the_snapshot(use_fake) -> None:  # type: ignore[no-untyped-def]
    use_fake(
        answer(
            sql="SELECT 1234567.5 AS net_sales_eur",
            metrics_used=["net_sales_eur", "total revenue"],
            assumptions=["Calendar month, EUR"],
        )
    )
    output = ask_cli("What were the net sales?", "--user", "carla", "--as-of", "2026-10-04")
    expected = (SNAPSHOT_DIR / "cli_ask_carla.txt").read_text(encoding="utf-8")
    assert output == expected


def test_the_answer_figure_comes_from_the_table_and_metrics_are_resolved_exactly(
    use_fake,  # type: ignore[no-untyped-def]
) -> None:
    use_fake(answer(sql="SELECT 41.5 AS x", metrics_used=["Net Sales", "net_sales_eur"]))
    output = ask_cli("q", "--user", "carla")
    # One value, named after the single exactly matching metric; the figure is the table's.
    assert "Net sales (EUR): 41.50" in output
    # The loose name is shown as text and labelled, never mapped to a definition.
    assert "Net Sales - not an identifiable metric" in output
    assert output.count("net_sales_eur - Net sales (EUR):") == 1


def test_anna_and_carla_get_different_numbers_for_the_same_sql(use_fake) -> None:  # type: ignore[no-untyped-def]
    sql = "SELECT count(*) AS n FROM fact_sales"
    use_fake(answer(sql=sql))
    carla = ask_cli("how many lines?", "--user", "carla")
    use_fake(answer(sql=sql))
    anna = ask_cli("how many lines?", "--user", "anna")
    carla_line = next(line for line in carla.splitlines() if line.startswith("n: "))
    anna_line = next(line for line in anna.splitlines() if line.startswith("n: "))
    assert carla_line != anna_line
    assert "regions 3" in anna and "all stores" in carla


def test_a_blocked_statement_shows_the_rule_and_was_not_run(use_fake) -> None:  # type: ignore[no-untyped-def]
    use_fake(answer(sql="SELECT * FROM raw.fact_sales"))
    output = ask_cli("show everything", "--user", "anna")
    assert "blocked by the safety checks and was not run" in output
    assert "BLOCKED by rule(s):" in output
    assert "raw_schema" in output


def test_clarification_and_refusal_are_readable(use_fake) -> None:  # type: ignore[no-untyped-def]
    use_fake(answer(needs_clarification=True, clarification_question="Which month?"))
    assert "I need one more detail before I can answer: Which month?" in ask_cli(
        "sales?", "--user", "carla"
    )
    use_fake(answer(intent="out_of_scope", approach="that is a write request"))
    refusal = ask_cli("delete the data", "--user", "carla")
    assert "I cannot answer this question. The model's reason: that is a write request" in refusal


def test_hungarian_labels_and_number_format(use_fake) -> None:  # type: ignore[no-untyped-def]
    use_fake(answer(sql="SELECT 1234567.5 AS x", metrics_used=["net_sales_eur"], language="hu"))
    output = ask_cli("Mennyi volt a nettó árbevétel?", "--user", "carla", "--lang", "hu")
    assert "Nettó árbevétel (EUR): 1 234 567,50" in output
    assert "Mit számoltunk" in output


def test_retry_is_off_by_default_and_the_validator_is_on(use_fake) -> None:  # type: ignore[no-untyped-def]
    fake = use_fake(answer(sql="SELECT nope FROM fact_sales"))
    output = ask_cli("q", "--user", "carla")
    assert len(fake.calls) == 1  # no second call: retry is off
    assert "could not be run" in output


def test_unknown_user_is_a_clear_error(use_fake) -> None:  # type: ignore[no-untyped-def]
    use_fake()
    result = runner.invoke(cli.app, ["ask", "q", "--user", "mallory"])
    assert result.exit_code != 0
    assert "unknown user" in result.output


def test_format_value_changes_only_the_appearance() -> None:
    assert format_value(1234.5, "en") == "1,234.50"
    assert format_value(7, "en") == "7"
    assert format_value(None, "en") == "-"
    assert format_value(True, "en") == "True"
    assert format_value("HU", "hu") == "HU"


def test_resolve_metrics_matches_names_exactly() -> None:
    layer = load_semantic_layer(PROJECT_ROOT / "semantic")
    resolved, unidentified = resolve_metrics(
        ["net_sales_eur", "net_sales_eur", "net sales", "NET_SALES_EUR"], layer
    )
    assert [metric.name for metric in resolved] == ["net_sales_eur"]
    assert unidentified == ["net sales", "NET_SALES_EUR"]


# --- eval sub-command ----------------------------------------------------------------------


def test_eval_hands_over_to_the_existing_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    from evals import run_eval

    seen: dict[str, object] = {}
    monkeypatch.setattr(run_eval, "main", lambda **kwargs: seen.update(kwargs))
    result = runner.invoke(
        cli.app, ["eval", "--mode", "semantic", "--profile", "claude_small", "--repetitions", "2"]
    )
    assert result.exit_code == 0, result.output
    assert (seen["mode"], seen["profile"], seen["suite"], seen["repetitions"]) == (
        "semantic",
        "claude_small",
        "development",
        2,
    )
    assert (seen["validator"], seen["retry"], seen["holdout_dir"]) == (True, False, None)


def test_the_holdout_suite_cannot_be_started_from_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    from evals import run_eval

    def must_not_run(**kwargs: object) -> None:
        raise AssertionError("the runner must not be reached")

    monkeypatch.setattr(run_eval, "main", must_not_run)
    result = runner.invoke(cli.app, ["eval", "--suite", "holdout"])
    assert result.exit_code != 0
    assert "only the development and security suites" in result.output
    assert "holdout-dir" not in runner.invoke(cli.app, ["eval", "--help"]).output


def test_the_user_option_is_required() -> None:
    """No default user: the caller must say whose permissions apply."""
    result = runner.invoke(cli.app, ["ask", "q"])
    assert result.exit_code == 2
    assert "--user" in result.output
