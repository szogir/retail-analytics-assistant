"""Heuristic check of the executed SQL against the named metric (no model, no database)."""

import io
from pathlib import Path

import pytest
from rich.console import Console

from retail_assistant.llm.schemas import SqlAnswer
from retail_assistant.pipeline import Answer
from retail_assistant.presentation import computed_panel
from retail_assistant.semantic.loader import load_semantic_layer
from retail_assistant.semantic.metric_check import check_metric
from retail_assistant.semantic.models import SemanticLayer

FULL_SQL = (
    "SELECT SUM((f.gross_amount - f.discount_amount - f.vat_amount) / fx.eur_rate) "
    "FROM fact_sales f JOIN dim_store s ON s.store_id = f.store_id "
    "JOIN fx_rate fx ON fx.rate_date = f.sales_date AND fx.currency = f.currency "
    "WHERE NOT f.is_cancelled AND NOT s.is_test_store"
)
NO_VAT_SQL = FULL_SQL.replace(" - f.vat_amount", "")


@pytest.fixture(scope="module")
def layer() -> SemanticLayer:
    return load_semantic_layer(Path(__file__).resolve().parents[1] / "semantic")


def _answer(sql: str, metrics: list[str]) -> Answer:
    model_answer = SqlAnswer(
        language="en",
        intent="metric_query",
        approach="x",
        sql=sql,
        metrics_used=metrics,
        assumptions=[],
        needs_clarification=False,
        clarification_question="",
    )
    return Answer("answered", "q", sql=sql, model_answer=model_answer)


def _panel_text(answer: Answer, layer: SemanticLayer) -> str:
    panel = computed_panel(
        answer, lang="en", user="carla", access=None, validator_on=True, layer=layer
    )
    console = Console(width=200, record=True, file=io.StringIO())
    console.print(panel)
    return console.export_text()


def test_full_net_sales_sql_has_nothing_missing(layer: SemanticLayer) -> None:
    metric = next(m for m in layer.metrics.metrics if m.name == "net_sales_eur")
    assert check_metric(metric, FULL_SQL).kind == "ok"


def test_net_sales_without_vat_is_reported(layer: SemanticLayer) -> None:
    metric = next(m for m in layer.metrics.metrics if m.name == "net_sales_eur")
    outcome = check_metric(metric, NO_VAT_SQL)
    assert outcome.kind == "missing" and outcome.missing == ("vat_amount",)


def test_unparsable_sql_gives_no_verdict_and_no_exception(layer: SemanticLayer) -> None:
    metric = next(m for m in layer.metrics.metrics if m.name == "net_sales_eur")
    assert check_metric(metric, "SELEC nonsense ((").kind == "unparsable"


def test_panel_warns_when_vat_is_missing_and_labels_both_parts(layer: SemanticLayer) -> None:
    text = _panel_text(_answer(NO_VAT_SQL, ["net_sales_eur"]), layer)
    assert "heuristic check: SQL does not reference vat_amount" in text
    assert "Metric named by the model" in text
    assert "SQL actually executed" in text


def test_panel_success_line_claims_no_correctness(layer: SemanticLayer) -> None:
    text = _panel_text(_answer(FULL_SQL, ["net_sales_eur"]), layer)
    assert "found no missing element" in text
    assert "not prove" in text or "does not prove" in text
    assert "✓" not in text and "OK" not in text.replace("NOT", "")


@pytest.mark.parametrize("metrics", [[], ["net sales"]])
def test_panel_without_a_catalogue_metric_says_no_check(
    layer: SemanticLayer, metrics: list[str]
) -> None:
    text = _panel_text(_answer(FULL_SQL, metrics), layer)
    assert "no catalogue metric named, no check" in text
