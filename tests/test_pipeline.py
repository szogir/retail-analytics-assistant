"""Tests for the context builder, the executor and the pipeline (fake LLM, no network)."""

import datetime as dt
from pathlib import Path

import pytest

from retail_assistant.config import PROJECT_ROOT
from retail_assistant.llm.base import LLMOutputError, LLMProviderError
from retail_assistant.llm.fake import DEFAULT_USAGE, FakeLLMClient
from retail_assistant.llm.profiles import load_profile
from retail_assistant.llm.schemas import SqlAnswer
from retail_assistant.pipeline import MAX_OUTPUT_TOKENS, Answer, ask, build_user_prompt
from retail_assistant.semantic.context import build_system_prompt, describe_schema, prompt_version
from retail_assistant.sql.executor import SqlExecutionError, execute_query

PROMPTS_DIR = PROJECT_ROOT / "config" / "prompts"
PROFILE = load_profile(PROJECT_ROOT / "config" / "models.yaml", "claude_small")
AS_OF = dt.date(2026, 10, 4)


def answer(**fields: object) -> SqlAnswer:
    base: dict[str, object] = {"language": "en", "intent": "metric_query", "approach": "thinking"}
    return SqlAnswer.model_validate({**base, **fields})


def run(fake: FakeLLMClient, db: Path, user: str = "carla") -> Answer:
    return ask(
        "How many stores?",
        user,
        "en",
        "naive",
        llm=fake,
        profile=PROFILE,
        db_path=db,
        prompts_dir=PROMPTS_DIR,
        as_of=AS_OF,
        validate=False,  # these tests cover the original path, which must stay unchanged
    )


# --- context builder ---------------------------------------------------------------------


def test_schema_description_lists_tables_and_columns(tiny_db: Path) -> None:
    lines = describe_schema(tiny_db).splitlines()
    assert lines[0] == "dim_store(store_id INTEGER, store_name VARCHAR)"
    assert lines[1].startswith("fx_rate(rate_date DATE, currency VARCHAR")


def test_naive_prompt_has_the_schema_and_no_business_rules(tiny_db: Path) -> None:
    prompt = build_system_prompt("naive", tiny_db, PROMPTS_DIR)
    assert "dim_store(store_id INTEGER" in prompt
    assert "{schema}" not in prompt
    # "Naive" means schema only: the prompt TEXT (without the generated schema) must not
    # contain any of the business rules the semantic layer adds on day 4.
    template = (PROMPTS_DIR / "sql_naive_v1.md").read_text(encoding="utf-8")
    for rule in ("cancelled", "test store", "currency", "VAT", "net sales"):
        assert rule.lower() not in template.lower(), rule
    assert prompt_version("naive") == "sql_naive_v1"


def test_an_unknown_mode_has_no_prompt() -> None:
    with pytest.raises(NotImplementedError):
        prompt_version("nonsense")  # type: ignore[arg-type]


def test_user_prompt_carries_the_date_and_question() -> None:
    text = build_user_prompt("Hány bolt van?", "hu", AS_OF)
    assert "2026-10-04" in text and "Hány bolt van?" in text and "hu" in text


# --- executor ------------------------------------------------------------------------------


def test_executor_returns_columns_and_rows(tiny_db: Path) -> None:
    result = execute_query(tiny_db, "SELECT store_id, store_name FROM dim_store ORDER BY 1")
    assert result.columns == ["store_id", "store_name"]
    assert result.rows == [(1, "A"), (2, "B"), (3, "C")]
    assert not result.truncated


def test_executor_limits_rows_and_reports_truncation(tiny_db: Path) -> None:
    result = execute_query(tiny_db, "SELECT * FROM dim_store", row_limit=2)
    assert len(result.rows) == 2
    assert result.truncated


def test_executor_is_read_only(tiny_db: Path) -> None:
    with pytest.raises(SqlExecutionError):
        execute_query(tiny_db, "DELETE FROM dim_store")
    assert len(execute_query(tiny_db, "SELECT * FROM dim_store").rows) == 3


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_text('/etc/passwd')",
        "COPY (SELECT 1) TO 'leak.csv'",
        "ATTACH 'other.duckdb' AS other",
        "INSTALL httpfs",
    ],
)
def test_executor_blocks_file_and_system_access(tiny_db: Path, sql: str, tmp_path: Path) -> None:
    # Checked on the installed DuckDB version: with external access off, even a read-only
    # connection cannot read or write files outside the database.
    with pytest.raises(SqlExecutionError):
        execute_query(tiny_db, sql)
    assert not Path("leak.csv").exists()


def test_executor_turns_database_errors_into_our_error(tiny_db: Path) -> None:
    with pytest.raises(SqlExecutionError):
        execute_query(tiny_db, "SELECT nope FROM dim_store")


def test_executor_interrupts_a_runaway_query(tiny_db: Path) -> None:
    slow = "SELECT count(*) FROM range(100000000000) a"
    with pytest.raises(SqlExecutionError):
        execute_query(tiny_db, slow, timeout_seconds=0.5)


# --- pipeline ------------------------------------------------------------------------------


def test_answered_question_carries_result_and_measurements(tiny_db: Path) -> None:
    fake = FakeLLMClient(responses=[answer(sql="SELECT COUNT(*) FROM dim_store")])
    result = run(fake, tiny_db)

    assert result.status == "answered"
    assert result.result is not None and result.result.rows == [(3,)]
    assert result.sql == "SELECT COUNT(*) FROM dim_store"
    assert result.cost_usd == pytest.approx(PROFILE.cost_usd(DEFAULT_USAGE))
    assert result.latency_ms == 5.0
    assert fake.calls[0].max_tokens == MAX_OUTPUT_TOKENS
    assert result.prompt_version == "sql_naive_v1"
    # The model got the stable system prompt and the dated question separately.
    call = fake.calls[0]
    assert "dim_store(" in call.system and "2026-10-04" not in call.system
    assert "2026-10-04" in call.user and "How many stores?" in call.user


def test_clarification_is_not_executed(tiny_db: Path) -> None:
    fake = FakeLLMClient(
        responses=[answer(needs_clarification=True, clarification_question="Which period?")]
    )
    result = run(fake, tiny_db)
    assert (result.status, result.message, result.result) == (
        "clarification",
        "Which period?",
        None,
    )


def test_out_of_scope_is_refused(tiny_db: Path) -> None:
    result = run(FakeLLMClient(responses=[answer(intent="out_of_scope", approach="no")]), tiny_db)
    assert result.status == "refused"


def test_missing_sql_is_invalid_output(tiny_db: Path) -> None:
    assert run(FakeLLMClient(responses=[answer(sql="  ")]), tiny_db).status == "invalid_output"


def test_failing_sql_becomes_a_status_not_an_exception(tiny_db: Path) -> None:
    result = run(FakeLLMClient(responses=[answer(sql="SELECT nope FROM dim_store")]), tiny_db)
    assert result.status == "sql_error"
    assert result.sql == "SELECT nope FROM dim_store"
    assert result.message


def test_llm_failures_become_statuses(tiny_db: Path) -> None:
    assert run(FakeLLMClient(responses=[LLMOutputError("bad")]), tiny_db).status == "invalid_output"
    assert run(FakeLLMClient(responses=[LLMProviderError("down")]), tiny_db).status == "llm_error"


def test_other_users_need_the_validated_path(tiny_db: Path) -> None:
    with pytest.raises(ValueError, match="not supported"):
        run(FakeLLMClient(responses=[answer()]), tiny_db, user="anna")
