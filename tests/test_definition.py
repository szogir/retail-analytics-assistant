"""Definition answers and how the frozen grading treats the new "definition" status."""

import datetime as dt
from pathlib import Path

import pytest

from evals.golden import load_golden_set
from evals.run_eval import grade, grade_primary
from evals.security_scoring import NO_EFFECT, classify, passed
from retail_assistant.config import PROJECT_ROOT
from retail_assistant.llm.fake import FakeLLMClient
from retail_assistant.llm.profiles import load_profile
from retail_assistant.llm.schemas import SqlAnswer
from retail_assistant.pipeline import Answer, ask
from retail_assistant.presentation import answer_text
from retail_assistant.semantic.loader import load_semantic_layer

PROMPTS_DIR = PROJECT_ROOT / "config" / "prompts"
SEMANTIC_DIR = PROJECT_ROOT / "semantic"
USERS_PATH = PROJECT_ROOT / "config" / "users.yaml"
PROFILE = load_profile(PROJECT_ROOT / "config" / "models.yaml", "claude_small")


def definition_answer(metrics: list[str], sql: str = "") -> FakeLLMClient:
    model = SqlAnswer.model_validate(
        {
            "language": "en",
            "intent": "definition",
            "approach": "x",
            "sql": sql,
            "metrics_used": metrics,
        }
    )
    return FakeLLMClient(responses=[model])


def run(fake: FakeLLMClient, db: Path, *, validate: bool = True, mode: str = "semantic") -> Answer:
    return ask(
        "What does net sales mean?",
        "carla",
        "en",
        mode,  # type: ignore[arg-type]
        llm=fake,
        profile=PROFILE,
        db_path=db,
        prompts_dir=PROMPTS_DIR,
        as_of=dt.date(2026, 10, 4),
        semantic_dir=SEMANTIC_DIR,
        validate=validate,
        users_path=USERS_PATH if validate else None,
    )


def test_exact_catalogue_name_gives_a_definition_without_running_sql(full_db_path: Path) -> None:
    answer = run(definition_answer(["net_sales_eur"], sql="DELETE FROM fact_sales"), full_db_path)
    assert answer.status == "definition"
    assert answer.message == "net_sales_eur"
    assert answer.result is None and answer.sql == ""  # the model's SQL is never used


@pytest.mark.parametrize(
    "metrics",
    [[], ["Net Sales"], ["net_sales_eur", "units_sold"], ["not_a_metric"]],
)
def test_no_exact_single_match_keeps_the_old_behaviour(
    full_db_path: Path, metrics: list[str]
) -> None:
    # Old behaviour for a definition answer without SQL: invalid output.
    answer = run(definition_answer(metrics), full_db_path)
    assert answer.status == "invalid_output"


def test_without_a_semantic_layer_there_is_no_catalogue_to_match(full_db_path: Path) -> None:
    fake = definition_answer(["net_sales_eur"])
    answer = ask(
        "What does net sales mean?",
        "carla",
        "en",
        "naive",
        llm=fake,
        profile=PROFILE,
        db_path=full_db_path,
        prompts_dir=PROMPTS_DIR,
        as_of=dt.date(2026, 10, 4),
        users_path=USERS_PATH,
    )
    assert answer.status == "invalid_output"


def test_the_legacy_path_never_returns_a_definition(full_db_path: Path) -> None:
    answer = run(definition_answer(["net_sales_eur"]), full_db_path, validate=False)
    assert answer.status == "invalid_output"


@pytest.mark.parametrize("kind", ["result", "clarification", "refusal", "result_scoped"])
def test_an_unknown_status_fails_every_kind_of_case(kind: str) -> None:
    """The frozen grading counts a "definition" answer as a failure, without exception."""
    cases = [c for c in load_golden_set() if c.expected.kind == kind]
    if not cases:
        pytest.skip(f"no development case of kind {kind}")
    answer = Answer("definition", "q", message="net_sales_eur")
    reference = None
    for case in cases:
        assert grade(case, answer, reference) == (False, False)
        assert grade_primary(case, answer, reference) is False


def test_security_scoring_gives_a_definition_no_credit() -> None:
    answer = Answer("definition", "q", message="net_sales_eur")
    outcome = classify(kind="refusal", attack="dml", answer=answer, reference=None, forbidden=None)
    assert outcome == NO_EFFECT
    assert passed("refusal", outcome, refusal_acceptable=False) is False


def test_the_definition_sentence_is_the_catalogues_text_not_the_models() -> None:
    layer = load_semantic_layer(SEMANTIC_DIR)
    metric = next(m for m in layer.metrics.metrics if m.name == "net_sales_eur")
    answer = Answer("definition", "q", message="net_sales_eur")
    text = answer_text(answer, "en", [metric])
    assert text.startswith("Definition of Net sales (EUR): ")
    assert metric.description.strip() in text
