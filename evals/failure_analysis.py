"""Heuristic failure analysis: which business rule did a failed answer miss?

What it does: reads one run file written by `evals.run_eval`, takes every data question
that failed the primary score and compares the model's SQL with the reference SQL of its
case. Each difference is labelled with the business rule it most likely violates (net
formula, test store, fiscal vs calendar year, ...). The counts are written as Markdown.

Why it exists: the project claims that a semantic layer adds the *business rules* that
column comments cannot. This report shows which rules are actually missing, so the
semantic files can be traced back to concrete failures (and not to guesses).

Where it sits in the pipeline: evaluation only (after a run, before semantic design).

IMPORTANT: the categories are HEURISTIC. They are text patterns on SQL, not a proof of
cause. One failed answer can break several rules at once, so the per-rule counts add up to
more than the number of failed answers, and a missing label never proves the rule was
handled correctly. Sample some failures by hand before relying on a count.
"""

import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer

from evals.golden import GOLDEN_SET_DIR, load_golden_set

HEURISTIC_NOTICE = (
    "The rule categories are heuristic text patterns on the model SQL versus the reference "
    "SQL, not proven causes. One failed answer can break several rules, so the counts add "
    "up to more than the number of failed answers."
)

RESULT_KINDS = ("result", "result_scoped")

# Labels for answers that never produced a comparable table.
NO_TABLE_STATUSES = ("sql_error", "clarification", "refused", "invalid_output")

_RETURN_EXCLUSION = re.compile(r"not\s+\w*\.?is_return|is_return\s*=\s*(false|0)")
_FX_MULTIPLICATION = re.compile(r"\*\s*\w*\.?eur_rate")


@dataclass(frozen=True)
class Analysis:
    """Aggregated result of the failure analysis.

    Attributes:
        mode: Prompt mode recorded in the run file (naive, commented, ...).
        data_questions: Number of data questions in the run.
        failed_questions: Data questions that failed the primary score.
        by_question: Rule label -> number of failed questions carrying it.
        by_case: Rule label -> number of distinct cases carrying it.
        failed_cases: Number of distinct cases with at least one failed question.
        data_cases: Number of distinct data cases in the run.
        repetitions: Repetitions recorded in the run file.
    """

    mode: str
    data_questions: int
    failed_questions: int
    by_question: Counter[str]
    by_case: Counter[str]
    failed_cases: int
    data_cases: int
    repetitions: int


def classify_sql(model_sql: str, reference_sql: str) -> list[str]:
    """Label the business rules the model SQL appears to miss.

    Why: the reference SQL encodes the business contract, so a rule that the reference
    uses and the model SQL does not (or the other way round) points at the missing rule.

    Design note: the alternative is to ask a second model to explain every failure. That
    is expensive and not reproducible. Plain patterns are cheap and deterministic, at the
    price of false labels, which is why the module docstring calls them heuristic.

    Args:
        model_sql: SQL written by the model.
        reference_sql: Reference SQL of the case.

    Returns:
        Rule labels in a fixed order; `other_unclassified` if no pattern matched.
    """
    model = model_sql.lower()
    reference = reference_sql.lower()
    labels: list[str] = []

    if "vat_amount" in reference and "vat_amount" not in model:
        labels.append("net_formula_no_vat")
    if "eur_rate" in reference:
        if "eur_rate" not in model:
            labels.append("fx_missing")
        elif _FX_MULTIPLICATION.search(model):
            labels.append("fx_direction")
    if "is_cancelled" in reference and "is_cancelled" not in model:
        labels.append("cancelled_not_excluded")
    if "is_test_store" in reference and "is_test_store" not in model:
        labels.append("test_store_not_excluded")

    reference_excludes_returns = bool(_RETURN_EXCLUSION.search(reference))
    model_excludes_returns = bool(_RETURN_EXCLUSION.search(model))
    if model_excludes_returns and not reference_excludes_returns:
        labels.append("returns_wrongly_excluded")
    if reference_excludes_returns and not model_excludes_returns:
        labels.append("returns_not_excluded")

    if "fiscal" in reference and "fiscal" not in model:
        labels.append("calendar_instead_of_fiscal")
    if "fiscal" in model and "fiscal" not in reference:
        labels.append("fiscal_instead_of_calendar")

    reference_counts_receipts = "count(distinct" in reference and "receipt" in reference
    if reference_counts_receipts and "avg(" in model and "count(distinct" not in model:
        labels.append("basket_average_of_averages")
    reference_counts_days = "count(distinct" in reference and "sales_date" in reference
    if reference_counts_days and "count(distinct" in model and "sales_date" not in model:
        labels.append("trading_day_not_used")

    return labels or ["other_unclassified"]


def analyze(
    results: Sequence[dict[str, Any]],
    references: dict[str, str],
    mode: str,
    repetitions: int,
) -> Analysis:
    """Classify every failed data question of a run.

    Args:
        results: The `results` list of a run file (one dict per question).
        references: Case id -> reference SQL.
        mode: Mode name from the run file, used in the report.
        repetitions: Repetition count from the run file.

    Returns:
        The aggregated counts.

    Raises:
        KeyError: If a failed data question has no reference SQL in `references`.
    """
    data = [r for r in results if r["expected_kind"] in RESULT_KINDS]
    by_question: Counter[str] = Counter()
    labels_per_case: dict[str, set[str]] = {}
    failed = [r for r in data if not r["primary"]]

    for row in failed:
        case_id = str(row["case_id"])
        if row["status"] in NO_TABLE_STATUSES:
            labels = [str(row["status"])]
        else:
            labels = classify_sql(str(row["sql"] or ""), references[case_id])
        by_question.update(labels)
        labels_per_case.setdefault(case_id, set()).update(labels)

    by_case: Counter[str] = Counter()
    for labels_of_case in labels_per_case.values():
        by_case.update(labels_of_case)

    return Analysis(
        mode=mode,
        data_questions=len(data),
        failed_questions=len(failed),
        by_question=by_question,
        by_case=by_case,
        failed_cases=len(labels_per_case),
        data_cases=len({str(r["case_id"]) for r in data}),
        repetitions=repetitions,
    )


def render_markdown(analysis: Analysis, run_file: Path) -> str:
    """Render the analysis as a Markdown report with the heuristic notice in the header.

    Args:
        analysis: Result of `analyze`.
        run_file: The analysed run file (named in the report for traceability).

    Returns:
        The report text.
    """
    lines = [
        f"# Failure analysis: `{analysis.mode}` mode",
        "",
        f"> **Heuristic.** {HEURISTIC_NOTICE}",
        "",
        f"- Run file: `{run_file.name}`",
        f"- Scope: data questions only: {analysis.data_questions} questions "
        f"({analysis.data_cases} cases, {analysis.repetitions} repetitions, 2 languages)",
        f"- Failed the primary score: {analysis.failed_questions} questions "
        f"in {analysis.failed_cases} of {analysis.data_cases} cases",
        "",
        "| rule label | failed questions | cases |",
        "|---|---|---|",
    ]
    for label, count in analysis.by_question.most_common():
        lines.append(f"| {label} | {count} | {analysis.by_case[label]} |")
    return "\n".join(lines) + "\n"


def load_references(golden_dir: Path = GOLDEN_SET_DIR) -> dict[str, str]:
    """Load the reference SQL of all result cases from a golden-set folder.

    Args:
        golden_dir: Development golden-set folder.

    Returns:
        Case id -> reference SQL.
    """
    references: dict[str, str] = {}
    for case in load_golden_set(golden_dir):
        if case.reference_sql:
            references[case.id] = case.reference_sql
    return references


def analyze_run_file(
    run_file: Path, expected_mode: str | None = None, golden_dir: Path = GOLDEN_SET_DIR
) -> Analysis:
    """Load a run file and analyse it.

    Args:
        run_file: JSON file written by `evals.run_eval`.
        expected_mode: If given, the file must have been produced in this mode.
        golden_dir: Development golden-set folder holding the reference SQL.

    Returns:
        The aggregated counts.

    Raises:
        ValueError: If the file's mode differs from `expected_mode`, or the run belongs
            to the holdout suite (this tool must never read sealed references).
    """
    data = json.loads(run_file.read_text(encoding="utf-8"))
    info = data["info"]
    # Why: the sealed holdout references must stay unseen during semantic development.
    if info.get("suite") != "development":
        raise ValueError("failure analysis only supports development runs")
    if expected_mode is not None and info["mode"] != expected_mode:
        raise ValueError(f"run file mode is {info['mode']!r}, expected {expected_mode!r}")
    return analyze(
        data["results"], load_references(golden_dir), str(info["mode"]), int(info["repetitions"])
    )


app = typer.Typer(add_completion=False, help="Heuristic failure analysis of a run file.")


@app.command()
def main(
    run_file: Annotated[Path, typer.Argument(help="run JSON written by evals.run_eval")],
    mode: Annotated[str, typer.Option(help="expected mode; checked against the file")] = "",
    out: Annotated[Path | None, typer.Option(help="write the Markdown here")] = None,
) -> None:
    """Print (or save) the failure analysis of one development run file."""
    try:
        analysis = analyze_run_file(run_file, expected_mode=mode or None)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    text = render_markdown(analysis, run_file)
    if out is None:
        typer.echo(text)
    else:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"Saved: {out}")


if __name__ == "__main__":
    app()
