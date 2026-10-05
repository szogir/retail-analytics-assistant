"""Pipeline tests for the backend layers (validator + per-user connection), with a fake model.

The fake client plays a model that writes forbidden or unauthorized SQL. The backend must stop
it even though the "model" did what an attacker asked.
"""

import datetime as dt
from pathlib import Path

import pytest

from evals.provenance import file_hash
from retail_assistant import pipeline
from retail_assistant.config import PROJECT_ROOT
from retail_assistant.llm.fake import FakeLLMClient
from retail_assistant.llm.profiles import load_profile
from retail_assistant.llm.schemas import SqlAnswer
from retail_assistant.pipeline import Answer, ask

PROMPTS_DIR = PROJECT_ROOT / "config" / "prompts"
USERS_PATH = PROJECT_ROOT / "config" / "users.yaml"
PROFILE = load_profile(PROJECT_ROOT / "config" / "models.yaml", "claude_small")
AS_OF = dt.date(2026, 10, 4)

FORBIDDEN_SQL = [
    "SELECT * FROM raw.fact_sales",
    "DELETE FROM fact_sales",
    "DROP TABLE fact_sales",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT 1; DROP TABLE fact_sales",
    "ATTACH 'x.duckdb' AS x",
    "SELECT query('SELECT * FROM fact_sales')",
]


def model_says(sql: str) -> FakeLLMClient:
    answer = SqlAnswer.model_validate(
        {"language": "en", "intent": "metric_query", "approach": "x", "sql": sql}
    )
    return FakeLLMClient(responses=[answer])


def run(
    sql: str, db: Path, user: str = "carla", validate: bool = True, users: Path | None = USERS_PATH
) -> Answer:
    return ask(
        "any question",
        user,
        "en",
        "naive",
        llm=model_says(sql),
        profile=PROFILE,
        db_path=db,
        prompts_dir=PROMPTS_DIR,
        as_of=AS_OF,
        validate=validate,
        users_path=users,
    )


@pytest.mark.parametrize("sql", FORBIDDEN_SQL)
def test_a_model_that_writes_forbidden_sql_is_blocked(sql: str, full_db_path: Path) -> None:
    before = file_hash(full_db_path)
    answer = run(sql, full_db_path)
    assert answer.status == "blocked"
    assert answer.result is None
    assert answer.blocked_rules
    assert answer.message.startswith("[")  # "[rule] 'token' ..." for people and machines
    assert file_hash(full_db_path) == before


def test_a_blocked_statement_is_never_executed(
    full_db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Order check: the validator runs first; a block opens no connection and runs nothing."""
    calls: list[str] = []

    def spy(name: str, original):  # type: ignore[no-untyped-def]
        def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(name)
            return original(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(pipeline, "validate_sql", spy("validate", pipeline.validate_sql))
    monkeypatch.setattr(
        pipeline, "open_user_connection", spy("connection", pipeline.open_user_connection)
    )
    monkeypatch.setattr(pipeline, "run_on_connection", spy("run", pipeline.run_on_connection))
    monkeypatch.setattr(pipeline, "execute_query", spy("legacy", pipeline.execute_query))

    assert run("DELETE FROM fact_sales", full_db_path).status == "blocked"
    assert calls == ["validate"]

    calls.clear()
    assert run("SELECT count(*) FROM fact_sales", full_db_path).status == "answered"
    assert calls == ["validate", "connection", "run"]


def test_validate_false_keeps_the_original_path(
    full_db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old measurements must stay reproducible: same call sequence, same statuses."""
    calls: list[str] = []

    def spy(name: str, original):  # type: ignore[no-untyped-def]
        def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(name)
            return original(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(pipeline, "validate_sql", spy("validate", pipeline.validate_sql))
    monkeypatch.setattr(
        pipeline, "open_user_connection", spy("connection", pipeline.open_user_connection)
    )
    monkeypatch.setattr(pipeline, "run_on_connection", spy("run", pipeline.run_on_connection))
    monkeypatch.setattr(pipeline, "execute_query", spy("legacy", pipeline.execute_query))

    ok = run("SELECT count(*) FROM fact_sales", full_db_path, validate=False, users=None)
    assert (ok.status, calls) == ("answered", ["legacy"])
    # What the validator would block is a plain SQL error or even a result on the old path:
    # nothing is "blocked" without validate=True.
    for sql in ("SELECT * FROM raw.fact_sales", "SELECT nope FROM fact_sales", "SELECT ((("):
        calls.clear()
        answer = run(sql, full_db_path, validate=False, users=None)
        assert answer.status == "sql_error"
        assert answer.blocked_rules == ()
        assert calls == ["legacy"]


def test_the_old_path_still_accepts_only_carla(full_db_path: Path) -> None:
    with pytest.raises(ValueError, match="not supported"):
        run("SELECT 1", full_db_path, user="anna", validate=False, users=None)


def test_unparsable_sql_is_a_sql_error_not_a_security_block(full_db_path: Path) -> None:
    answer = run("SELECT (((", full_db_path)
    assert answer.status == "sql_error"
    assert answer.blocked_rules == ()


def test_the_same_sql_gives_anna_and_carla_different_answers(full_db_path: Path) -> None:
    sql = "SELECT count(*) FROM fact_sales"
    anna = run(sql, full_db_path, user="anna")
    carla = run(sql, full_db_path, user="carla")
    assert anna.status == carla.status == "answered"
    assert anna.result is not None and carla.result is not None
    assert anna.result.rows != carla.result.rows


def test_an_unauthorized_question_returns_only_the_users_own_rows(full_db_path: Path) -> None:
    # Anna asks for ALL stores; she gets her own three, not an error and not the whole chain.
    answer = run("SELECT store_id FROM dim_store ORDER BY 1", full_db_path, user="anna")
    assert answer.result is not None
    assert [row[0] for row in answer.result.rows] == [8, 9, 10]


def test_unknown_user_and_missing_users_file_are_errors(full_db_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown user"):
        run("SELECT 1", full_db_path, user="mallory")
    with pytest.raises(ValueError, match="users_path"):
        run("SELECT 1", full_db_path, users=None)


def test_model_refusals_and_clarifications_never_reach_the_backend(full_db_path: Path) -> None:
    refusal = SqlAnswer.model_validate(
        {"language": "en", "intent": "out_of_scope", "approach": "no"}
    )
    answer = ask(
        "q",
        "anna",
        "en",
        "naive",
        llm=FakeLLMClient(responses=[refusal]),
        profile=PROFILE,
        db_path=full_db_path,
        prompts_dir=PROMPTS_DIR,
        as_of=AS_OF,
        validate=True,
        users_path=USERS_PATH,
    )
    assert answer.status == "refused"
