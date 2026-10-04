"""Evaluation runner: asks every golden question, grades the answers, writes the report.

What it does: for each golden case and language it calls the pipeline, compares the result
with the reference SQL result (execution accuracy) and writes `evals/reports/latest.md`.

Why it exists: it is the yardstick of the project. Every change to the prompt, the semantic
layer or the model is judged by running this and reading the numbers.

Where it sits in the pipeline: evaluation only; it drives the whole pipeline from outside.

Usage:
    uv run python -m evals.run_eval --mode naive --profile claude_small
    uv run python -m evals.run_eval --mode naive --profile claude_small --save-baseline
"""

import datetime as dt
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated

import typer

from evals.compare import compare_tables
from evals.golden import GoldenCase, load_golden_set
from evals.provenance import case_hash, file_hash, require_frozen
from evals.report import (
    CaseResult,
    RunInfo,
    load_baseline,
    render_report,
    save_baseline,
    today_iso,
)
from evals.suites import suite_directory
from retail_assistant.config import Settings
from retail_assistant.llm.base import LLMClient
from retail_assistant.llm.factory import create_llm
from retail_assistant.llm.profiles import ModelProfile
from retail_assistant.llm.schemas import SqlAnswer
from retail_assistant.pipeline import MAX_OUTPUT_TOKENS, Answer, Language, ask
from retail_assistant.semantic.context import Mode, build_system_prompt, prompt_version
from retail_assistant.sql.executor import QueryResult, execute_query

EVALS_DIR = Path(__file__).parent
REPORT_PATH = EVALS_DIR / "reports" / "latest.md"
BASELINE_PATH = EVALS_DIR / "baseline.json"
RUNS_DIR = EVALS_DIR / "runs"

app = typer.Typer(add_completion=False, help="Run the golden-set evaluation.")


def grade(case: GoldenCase, answer: Answer, reference: QueryResult | None) -> tuple[bool, bool]:
    """Grade one answer against what the case expects.

    Args:
        case: The golden case.
        answer: What the pipeline returned.
        reference: The result of the case's reference SQL (None for cases without a table).

    Returns:
        (strict pass, lenient pass).
    """
    kind = case.expected.kind
    if kind == "clarification":
        # The right behaviour is to ask, not to guess: any SQL answer is a failure.
        passed = answer.status == "clarification" and bool(answer.message.strip())
        return passed, passed
    if kind == "refusal":
        # Day 3: only the model's own refusal counts. From day 5 the validator's block counts too.
        passed = answer.status == "refused"
        return passed, passed

    # kind is "result" or "result_scoped": the result table must match the reference table.
    if answer.status != "answered" or answer.result is None or reference is None:
        return False, False
    if reference.truncated or answer.result.truncated:
        return False, False
    comparison = compare_tables(reference.rows, answer.result.rows, case.order_sensitive)
    return comparison.strict, comparison.lenient


def assumptions_match(case: GoldenCase, answer: Answer, lang: Language) -> bool:
    """Check preregistered explanation topics without an additional model judge.

    This is a lexical proxy, not proof of semantic correctness. The full text is
    retained for audit; negation and unusual paraphrases still need human inspection.
    """
    patterns = case.assumption_patterns.get(lang, [])
    if not patterns:
        return True
    if answer.model_answer is None:
        return False
    text = " ".join(answer.model_answer.assumptions)
    return all(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def grade_primary(case: GoldenCase, answer: Answer, reference: QueryResult | None) -> bool:
    """Score numerical accuracy with strict tolerance and optional extra columns."""
    if case.expected.kind not in ("result", "result_scoped"):
        return grade(case, answer, reference)[0]
    if answer.status != "answered" or answer.result is None or reference is None:
        return False
    if answer.result.truncated or reference.truncated:
        return False
    return compare_tables(reference.rows, answer.result.rows, case.order_sensitive).primary


def run_evaluation(
    cases: Sequence[GoldenCase],
    *,
    llm: LLMClient,
    profile: ModelProfile,
    mode: Mode,
    db_path: Path,
    prompts_dir: Path,
    languages: Sequence[Language],
) -> list[CaseResult]:
    """Ask every question of every case and grade the answers.

    Args:
        cases: The golden cases.
        llm: The model client (real, or a fake in tests).
        profile: Model profile, used for the cost.
        mode: "naive" or "semantic".
        db_path: The DuckDB file.
        prompts_dir: Folder with the versioned prompt files.
        languages: Which question languages to ask.

    Returns:
        One graded result per (case, language) that has a question text.
    """
    results: list[CaseResult] = []
    for case in cases:
        reference = execute_query(db_path, case.reference_sql) if case.reference_sql else None
        if reference is not None and reference.truncated:
            raise ValueError(f"Reference result truncated for case {case.id}")
        for lang in languages:
            question = case.questions.en if lang == "en" else case.questions.hu
            if question is None:
                continue  # no translation for this case yet
            answer = ask(
                question,
                case.user,
                lang,
                mode,
                llm=llm,
                profile=profile,
                db_path=db_path,
                prompts_dir=prompts_dir,
                as_of=case.as_of_date,
            )
            strict, lenient = grade(case, answer, reference)
            results.append(
                CaseResult(
                    case_id=case.id,
                    lang=lang,
                    category=case.category,
                    expected_kind=case.expected.kind,
                    status=answer.status,
                    strict=strict,
                    lenient=lenient,
                    latency_ms=answer.latency_ms,
                    cost_usd=answer.cost_usd,
                    sql=answer.sql,
                    message=answer.message,
                    primary=grade_primary(case, answer, reference),
                    assumptions_ok=assumptions_match(case, answer, lang),
                    assumptions=answer.model_answer.assumptions if answer.model_answer else [],
                    tags=case.tags,
                )
            )
    return results


@app.command()
def main(
    mode: Annotated[str, typer.Option(help="naive, commented or semantic")] = "naive",
    profile: Annotated[str, typer.Option(help="profile name from config/models.yaml")] = "",
    lang: Annotated[str, typer.Option(help="en, hu or both")] = "both",
    save_baseline_flag: Annotated[
        bool, typer.Option("--save-baseline", help="store a baseline inside the selected suite")
    ] = False,
    limit: Annotated[int, typer.Option(min=0, help="only the first N cases (0 = all)")] = 0,
    suite: Annotated[str, typer.Option(help="development or holdout")] = "development",
    repetitions: Annotated[int, typer.Option(min=1, max=3)] = 1,
    holdout_dir: Annotated[
        Path | None, typer.Option(help="External holdout path (or HOLDOUT_DIR)")
    ] = None,
) -> None:
    """Run the evaluation with a real model and write the report."""
    # Explicit lookup tables instead of casts: an unknown value fails with a clear message
    # and mypy can see that the values have the right types.
    modes: dict[str, Mode] = {"naive": "naive", "commented": "commented", "semantic": "semantic"}
    language_choices: dict[str, list[Language]] = {"en": ["en"], "hu": ["hu"], "both": ["en", "hu"]}
    if mode not in modes:
        raise typer.BadParameter("mode must be naive, commented or semantic")
    if lang not in language_choices:
        raise typer.BadParameter("lang must be 'en', 'hu' or 'both'")
    run_mode = modes[mode]
    languages = language_choices[lang]

    if suite not in ("development", "holdout"):
        raise typer.BadParameter("suite must be development or holdout")
    try:
        directory = suite_directory(suite, holdout_dir)
    except (ValueError, FileNotFoundError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    cases = load_golden_set(directory)
    settings = Settings()
    require_frozen(directory, cases, settings.db_path)
    if suite == "holdout" and (limit or lang != "both" or repetitions != 3):
        raise typer.BadParameter(
            "Final holdout runs require both languages, no limit, 3 repetitions"
        )
    setup = create_llm(settings, profile or None)
    if limit:
        cases = cases[:limit]
    prompts_dir = settings.config_dir / "prompts"

    info = RunInfo(
        mode=mode,
        profile=setup.profile.name,
        model=setup.profile.model,
        prompt_version=prompt_version(run_mode),
        price_date=setup.profile.price_date.isoformat(),
        run_date=today_iso(),
        max_tokens=MAX_OUTPUT_TOKENS,
        suite=suite,
        case_hash=case_hash(cases),
        database_hash=file_hash(settings.db_path),
        prompt_hash=hashlib.sha256(
            build_system_prompt(run_mode, settings.db_path, prompts_dir).encode()
        ).hexdigest(),
        repetitions=repetitions,
        config_hash=file_hash(settings.config_dir / "models.yaml"),
        scoring_hash=hashlib.sha256(
            (file_hash(Path(__file__)) + file_hash(EVALS_DIR / "compare.py")).encode()
        ).hexdigest(),
        schema_hash=hashlib.sha256(
            json.dumps(SqlAnswer.model_json_schema(), sort_keys=True).encode()
        ).hexdigest(),
    )
    output_dir = directory / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = output_dir / f"{setup.profile.name}_baseline.json"
    baseline = load_baseline(baseline_path, info)
    # Validate identities before incurring model-call costs. The immutable run dump
    # is written before the convenience report, so a reporting error loses no results.
    typer.echo(f"Running {len(cases)} cases, mode={mode}, profile={setup.profile.name} ...")
    results: list[CaseResult] = []
    for repeat in range(1, repetitions + 1):
        batch = run_evaluation(
            cases,
            llm=setup.client,
            profile=setup.profile,
            mode=run_mode,
            db_path=settings.db_path,
            prompts_dir=prompts_dir,
            languages=languages,
        )
        results.extend(replace(result, repeat=repeat) for result in batch)
    report_path = output_dir / "latest.md"

    # The full per-question dump (SQL, messages) is for debugging and is not versioned.
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dump = output_dir / f"{stamp}_{mode}_{info.profile}.json"
    dump.write_text(
        json.dumps({"info": asdict(info), "results": [asdict(r) for r in results]}, indent=2),
        encoding="utf-8",
    )
    report_path.write_text(render_report(info, results, baseline, len(cases)), encoding="utf-8")

    if save_baseline_flag:
        save_baseline(baseline_path, info, results)
        typer.echo(f"Baseline saved: {baseline_path}")
    strict = sum(r.strict for r in results)
    typer.echo(f"Strict accuracy: {strict}/{len(results)}. Report: {report_path}")


if __name__ == "__main__":
    app()
