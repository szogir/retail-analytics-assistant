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
import inspect
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated

import typer

from evals.compare import compare_tables
from evals.golden import GoldenCase, load_golden_set
from evals.holdout_commitment import verify_commitment
from evals.provenance import case_hash, file_hash, require_frozen, source_fingerprint
from evals.report import (
    CaseResult,
    RunInfo,
    baseline_from_run_file,
    load_baseline,
    render_report,
    save_baseline,
    today_iso,
)
from evals.security_scoring import classify, passed
from evals.security_suite import SECURITY_SUITE_DIR, SecurityCase, load_security_suite
from evals.suites import suite_directory
from retail_assistant.config import Settings
from retail_assistant.llm.base import LLMClient
from retail_assistant.llm.factory import create_llm
from retail_assistant.llm.profiles import ModelProfile
from retail_assistant.llm.schemas import SqlAnswer
from retail_assistant.pipeline import MAX_OUTPUT_TOKENS, Answer, Language, ask
from retail_assistant.semantic.context import Mode, build_system_prompt, prompt_version
from retail_assistant.semantic.loader import load_semantic_layer
from retail_assistant.sql.executor import QueryResult, execute_query

EVALS_DIR = Path(__file__).parent
REPORT_PATH = EVALS_DIR / "reports" / "latest.md"
BASELINE_PATH = EVALS_DIR / "baseline.json"
RUNS_DIR = EVALS_DIR / "runs"

app = typer.Typer(add_completion=False, help="Run the golden-set evaluation.")

# The functions whose logic decides whether an answer counts as correct. Together with
# compare.py (table matching and tolerances) they define the "scoring" of a run.
SCORING_FUNCTIONS = ("grade", "assumptions_match", "grade_primary")


def scoring_hash() -> str:
    """Fingerprint the code that decides correctness, and nothing else.

    Why: two runs are only comparable if they were graded by the same logic. The old hash
    covered the whole of this file, so adding a command-line option (no effect on grading)
    invalidated every earlier run. Now only the grading functions and compare.py count.

    Design note: the alternative, hashing the whole file, is safer against forgotten
    dependencies but makes unrelated edits break comparisons. `run_evaluation` is not
    included either: it only passes values to these functions, and tests cover it. The
    output schema has its own hash (`schema_hash`) in the run info.

    Returns:
        A SHA-256 hex digest of the syntax trees of the scoring code.
    """
    this_module = sys.modules[__name__]
    sources = [inspect.getsource(getattr(this_module, name)) for name in SCORING_FUNCTIONS]
    sources.append((EVALS_DIR / "compare.py").read_text(encoding="utf-8"))
    return source_fingerprint(sources)


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
    semantic_dir: Path | None = None,
    validate: bool = False,
    users_path: Path | None = None,
    user_override: str = "",
    retry: bool = False,
) -> list[CaseResult]:
    """Ask every question of every case and grade the answers.

    Args:
        cases: The golden cases.
        llm: The model client (real, or a fake in tests).
        profile: Model profile, used for the cost.
        mode: "naive", "commented" or "semantic".
        db_path: The DuckDB file.
        prompts_dir: Folder with the versioned prompt files.
        languages: Which question languages to ask.
        semantic_dir: Folder with the semantic files; needed for the "semantic" mode.
        validate: Backend protection on (validator + per-user connection), see `pipeline.ask`.
        users_path: `users.yaml`, needed when `validate` is on.
        user_override: Ask every question as this user instead of the case's own user.
        retry: One self-correction retry after a SQL error or block (needs `validate`).

    Returns:
        One graded result per (case, language) that has a question text.
    """
    results: list[CaseResult] = []
    for case in cases:
        reference = execute_query(db_path, case.reference_sql) if case.reference_sql else None
        if reference is not None and reference.truncated:
            raise ValueError(f"Reference result truncated for case {case.id}")
        forbidden: QueryResult | None = None
        if isinstance(case, SecurityCase) and case.forbidden_reference_sql:
            forbidden = execute_query(db_path, case.forbidden_reference_sql)
        for lang in languages:
            question = case.questions.en if lang == "en" else case.questions.hu
            if question is None:
                continue  # no translation for this case yet
            answer = ask(
                question,
                user_override or case.user,
                lang,
                mode,
                llm=llm,
                profile=profile,
                db_path=db_path,
                prompts_dir=prompts_dir,
                as_of=case.as_of_date,
                semantic_dir=semantic_dir,
                validate=validate,
                users_path=users_path,
                retry=retry,
            )
            strict, lenient = grade(case, answer, reference)
            # Security scoring is separate from `grade` (frozen): it also knows the backend's
            # block, and tells who stopped an attack. Only security and permission cases.
            security_outcome, security_pass = "", False
            if case.category in ("security", "permission"):
                security_outcome = classify(
                    kind=case.expected.kind,
                    attack=getattr(case, "attack", ""),
                    answer=answer,
                    reference=reference,
                    forbidden=forbidden,
                    order_sensitive=case.order_sensitive,
                )
                security_pass = passed(
                    case.expected.kind, security_outcome, getattr(case, "refusal_acceptable", False)
                )
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
                    security_outcome=security_outcome,
                    security_pass=security_pass,
                    user=user_override or case.user,
                    retried=answer.retried,
                    retry_succeeded=answer.retry_succeeded,
                    first_status=answer.first_status,
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
    suite: Annotated[str, typer.Option(help="development, security or holdout")] = "development",
    validator: Annotated[
        bool,
        typer.Option(
            "--validator/--no-validator",
            help="backend protection: SQL validator + per-user filtered connection",
        ),
    ] = False,
    retry: Annotated[
        bool,
        typer.Option(
            "--retry/--no-retry",
            help="one self-correction retry after a SQL error or block (needs --validator)",
        ),
    ] = False,
    user: Annotated[
        str, typer.Option(help="ask every question as this user (default: the case's user)")
    ] = "",
    repetitions: Annotated[int, typer.Option(min=1, max=3)] = 1,
    compare_to: Annotated[
        Path | None,
        typer.Option(help="Run dump (.json) of an earlier run to list improved/regressed against"),
    ] = None,
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

    if suite not in ("development", "security", "holdout"):
        raise typer.BadParameter("suite must be development, security or holdout")
    if suite == "holdout" and (validator or user):
        raise typer.BadParameter("the holdout is spent; it is not run with new options")
    if suite == "security" and not validator:
        raise typer.BadParameter("the security suite needs --validator (restricted users)")
    if retry and not validator:
        raise typer.BadParameter("--retry needs --validator")
    if retry and suite != "development":
        # Decision 17: the security suite is not re-run with retry (the backend never
        # blocked anything live), and the holdout is spent.
        raise typer.BadParameter("--retry is only measured on the development suite")
    cases: Sequence[GoldenCase]
    if suite == "security":
        directory = SECURITY_SUITE_DIR
        cases = load_security_suite(directory)
    else:
        try:
            directory = suite_directory(suite, holdout_dir)
        except (ValueError, FileNotFoundError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        cases = load_golden_set(directory)
    settings = Settings()
    manifest_hash = ""
    if suite == "holdout":
        manifest_hash = verify_commitment(directory, settings.db_path)
    elif suite == "development":
        normalized = require_frozen(directory, cases, settings.db_path)
        if normalized:
            # The frozen hashes were taken on CRLF files; say so instead of passing silently.
            typer.echo(
                f"Frozen files verified with line-ending normalization: {len(normalized)} files "
                "(content identical, see Decision 21)."
            )
    if suite == "holdout" and (limit or lang != "both" or repetitions != 3):
        raise typer.BadParameter(
            "Final holdout runs require both languages, no limit, 3 repetitions"
        )
    setup = create_llm(settings, profile or None)
    if limit:
        cases = list(cases)[:limit]
    prompts_dir = settings.config_dir / "prompts"
    # Only the semantic mode reads the semantic files; the other modes must not be affected
    # by them, so their run info carries no semantic fingerprint.
    semantic_dir = settings.semantic_dir if run_mode == "semantic" else None
    layer = load_semantic_layer(semantic_dir) if semantic_dir is not None else None

    info = RunInfo(
        mode=mode,
        profile=setup.profile.name,
        model=setup.profile.model,
        prompt_version=prompt_version(run_mode),
        price_date=setup.profile.price_date.isoformat(),
        thinking=setup.profile.thinking_setting,
        run_date=today_iso(),
        max_tokens=MAX_OUTPUT_TOKENS,
        suite=suite,
        case_hash=case_hash(cases),
        database_hash=file_hash(settings.db_path),
        prompt_hash=hashlib.sha256(
            build_system_prompt(run_mode, settings.db_path, prompts_dir, semantic_dir).encode()
        ).hexdigest(),
        repetitions=repetitions,
        config_hash=file_hash(settings.config_dir / "models.yaml"),
        scoring_hash=scoring_hash(),
        schema_hash=hashlib.sha256(
            json.dumps(SqlAnswer.model_json_schema(), sort_keys=True).encode()
        ).hexdigest(),
        holdout_manifest_hash=manifest_hash,
        holdout_verified=bool(manifest_hash),
        data_case_count=sum(c.expected.kind in ("result", "result_scoped") for c in cases),
        semantic_files=layer.file_hashes if layer else {},
        semantic_versions=layer.file_versions if layer else {},
        validator=validator,
        retry=retry,
        user=user,
    )
    users_path = settings.config_dir / "users.yaml"
    output_dir = directory / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = output_dir / f"{setup.profile.name}_baseline.json"
    # Design note: --compare-to replaces the profile baseline file. The alternative, comparing
    # to both, would mix two different questions ("versus the first naive run" and "versus the
    # previous mode") in one section.
    if compare_to is not None:
        baseline: dict[str, dict[str, object]] | None = baseline_from_run_file(compare_to, info)
        baseline_label = f"earlier run {compare_to.name}"
    else:
        baseline = load_baseline(baseline_path, info)
        baseline_label = "baseline"
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
            semantic_dir=semantic_dir,
            validate=validator,
            users_path=users_path,
            user_override=user,
            retry=retry,
        )
        results.extend(replace(result, repeat=repeat) for result in batch)
    report_path = output_dir / "latest.md"

    # The full per-question dump (SQL, messages) is for debugging and is not versioned.
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    tag = ("_validated" if validator else "") + ("_retry" if retry else "")
    dump = output_dir / f"{stamp}_{mode}_{info.profile}{tag}.json"
    # Do not label a run verified if sealed files changed while it ran.
    if suite == "holdout" and verify_commitment(directory, settings.db_path) != manifest_hash:
        raise ValueError("Holdout manifest changed during evaluation")
    dump.write_text(
        json.dumps({"info": asdict(info), "results": [asdict(r) for r in results]}, indent=2),
        encoding="utf-8",
    )
    report_path.write_text(
        render_report(info, results, baseline, len(cases), baseline_label), encoding="utf-8"
    )

    if save_baseline_flag:
        save_baseline(baseline_path, info, results)
        typer.echo(f"Baseline saved: {baseline_path}")
    strict = sum(r.strict for r in results)
    typer.echo(f"Strict accuracy: {strict}/{len(results)}. Report: {report_path}")


if __name__ == "__main__":
    app()
