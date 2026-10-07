"""Evaluation results: data types, metrics, baseline comparison and the Markdown report.

What it does: turns the list of per-case results into the numbers the project reports
(accuracy by category and language, security pass rate, invalid-output rate, latency
percentiles, cost per question) and writes them to `evals/reports/latest.md`.

Why it exists: "every change is measured by an evaluation run" only works if the numbers
are always computed and shown the same way. The baseline file stores the per-case outcome
of a reference run, so a later report can list exactly which cases improved or regressed.

Where it sits in the pipeline: evaluation only (reporting step of the eval runner).
"""

import datetime as dt
import json
import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class CaseResult:
    """The graded outcome of one question (one case in one language).

    Attributes:
        case_id: Golden-set id.
        lang: Language of the question that was asked ("en" or "hu").
        category: Category of the case (aggregation, ratio, security, ...).
        expected_kind: What a correct answer looks like (result, clarification, refusal).
        status: What the pipeline did (see `retail_assistant.pipeline.Status`).
        strict: Passed with the strict comparison.
        lenient: Passed with the lenient comparison.
        latency_ms: Time of the model call.
        cost_usd: Price of the model call.
        sql: The SQL the model wrote (empty if none).
        message: Clarification, refusal reason or error text.
    """

    case_id: str
    lang: str
    category: str
    expected_kind: str
    status: str
    strict: bool
    lenient: bool
    latency_ms: float
    cost_usd: float
    sql: str = ""
    message: str = ""
    primary: bool = False
    assumptions_ok: bool = True
    assumptions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    repeat: int = 1
    # Security scoring (evals/security_scoring.py): who stopped the attack, and whether the case
    # passed. Empty for cases that are not security or permission cases.
    security_outcome: str = ""
    security_pass: bool = False
    # Who asked: the case's own user, or the `--user` override. Shown per case in the security
    # table, so a restricted user's cases are visibly run as that user.
    user: str = ""
    # Self-correction retry (day 5): whether a second model call was made for this
    # question, and whether it ended in a result table.
    retried: bool = False
    retry_succeeded: bool = False
    # Status of the first attempt (also when a retry changed the final status). Empty in run
    # files written before this field existed.
    first_status: str = ""

    @property
    def key(self) -> str:
        """Identifier used in the baseline file, e.g. ``004:hu``."""
        suffix = f":r{self.repeat}" if self.repeat != 1 else ""
        return f"{self.case_id}:{self.lang}{suffix}"


@dataclass(frozen=True)
class RunInfo:
    """Which configuration produced a run (printed at the top of the report)."""

    mode: str
    profile: str
    model: str
    prompt_version: str
    price_date: str
    run_date: str
    max_tokens: int
    suite: str = "legacy"
    case_hash: str = ""
    database_hash: str = ""
    prompt_hash: str = ""
    repetitions: int = 1
    scoring_version: str = "execution_v2"
    config_hash: str = ""
    scoring_hash: str = ""
    schema_hash: str = ""
    holdout_manifest_hash: str = ""
    holdout_verified: bool = False
    data_case_count: int = 0
    # Semantic mode only: SHA-256 and version of each semantic YAML file (empty otherwise).
    semantic_files: dict[str, str] = field(default_factory=dict)
    semantic_versions: dict[str, int] = field(default_factory=dict)
    # Backend configuration of the run (day 5). Defaults describe the earlier runs, which had
    # no validator, no retry and used each case's own user ("" = the case's user).
    validator: bool = False
    retry: bool = False
    user: str = ""
    # The thinking setting sent with every request ("" in run files from before it was recorded).
    thinking: str = ""


def percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile (e.g. fraction 0.95 = p95); 0.0 for an empty list.

    Design note: nearest-rank needs no interpolation, so every reported latency is a
    latency that really happened, and the rule is easy to explain.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def _rate(results: Sequence[CaseResult], predicate: Callable[[CaseResult], bool]) -> float:
    return sum(predicate(r) for r in results) / len(results) if results else 0.0


def _group_accuracy(
    results: Sequence[CaseResult], key: Callable[[CaseResult], str]
) -> dict[str, tuple[int, int, int]]:
    """Per group: (cases, strict passes, lenient passes)."""
    groups: dict[str, list[CaseResult]] = defaultdict(list)
    for result in results:
        groups[key(result)].append(result)
    return {
        name: (len(items), sum(r.strict for r in items), sum(r.lenient for r in items))
        for name, items in sorted(groups.items())
    }


def compare_to_baseline(
    results: Sequence[CaseResult],
    baseline: dict[str, dict[str, object]],
    metric: Literal["strict", "primary"] = "strict",
) -> tuple[list[str], list[str]]:
    """List the cases that improved or regressed on the selected outcome.

    Args:
        results: The current run.
        baseline: The `results` object of the baseline file, keyed like ``004:hu``.
        metric: Strict legacy accuracy, or primary execution accuracy on data cases.

    Returns:
        (improved keys, regressed keys). Cases that are not in the baseline are ignored.
    """
    improved: list[str] = []
    regressed: list[str] = []
    for result in results:
        if metric == "primary" and result.expected_kind not in ("result", "result_scoped"):
            continue
        before = baseline.get(result.key)
        if before is None or metric not in before:
            continue
        if getattr(result, metric) and not before[metric]:
            improved.append(result.key)
        elif before[metric] and not getattr(result, metric):
            regressed.append(result.key)
    return improved, regressed


def save_baseline(path: Path, info: RunInfo, results: Sequence[CaseResult]) -> None:
    """Write the per-case outcomes of a run as the new baseline (versioned in git)."""
    document = {
        "info": asdict(info),
        "case_count": len({r.case_id for r in results}),
        "question_count": len(results),
        "results": {
            r.key: {
                "strict": r.strict,
                "lenient": r.lenient,
                "primary": r.primary,
                "status": r.status,
            }
            for r in results
        },
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# Run settings that must be identical for two runs to be comparable. The prompt, mode and
# semantic files are deliberately NOT here: they are the things an experiment changes.
_COMPARABLE_KEYS = (
    "suite",
    "case_hash",
    "database_hash",
    "scoring_version",
    "repetitions",
    "model",
    "max_tokens",
    "config_hash",
    "scoring_hash",
    "schema_hash",
    "data_case_count",
    "holdout_manifest_hash",
    "holdout_verified",
)


def _require_comparable(recorded: dict[str, object], info: RunInfo) -> None:
    """Raise if an earlier run was made with different settings than the current one."""
    for key in _COMPARABLE_KEYS:
        if recorded.get(key) != getattr(info, key):
            raise ValueError(f"Incompatible baseline: {key}")


def load_baseline(path: Path, info: RunInfo | None = None) -> dict[str, dict[str, object]] | None:
    """Read the `results` object of the baseline file, or None if there is no baseline yet."""
    if not path.is_file():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    if info is not None:
        _require_comparable(document["info"], info)
    results: dict[str, dict[str, object]] = document["results"]
    return results


def baseline_from_run_file(path: Path, info: RunInfo) -> dict[str, dict[str, object]]:
    """Turn a saved run dump into a per-question baseline for the improved/regressed lists.

    Why: the main question is "what changed compared with the previous mode", for example
    semantic versus commented. A run dump already holds every graded question, so it can be
    the reference directly, without a separate baseline file.

    Args:
        path: A ``<timestamp>_<mode>_<profile>.json`` file written by the eval runner.
        info: The current run; the old run must have been made with identical settings.

    Returns:
        Outcomes keyed like ``004:hu`` (``004:hu:r2`` for repetition 2).

    Raises:
        ValueError: If the earlier run used different settings (case set, database, model,
            scoring, ...), because a comparison would then be misleading.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    _require_comparable(document["info"], info)
    outcomes: dict[str, dict[str, object]] = {}
    for raw in document["results"]:
        result = CaseResult(**raw)
        outcomes[result.key] = {
            "strict": result.strict,
            "lenient": result.lenient,
            "primary": result.primary,
            "status": result.status,
        }
    return outcomes


def _semantic_header(info: RunInfo) -> list[str]:
    """Header lines naming the exact semantic files (version and SHA-256) behind a run."""
    return [
        f"- Semantic file `{name}` v{info.semantic_versions.get(name, '?')} SHA-256: `{digest}`"
        for name, digest in sorted(info.semantic_files.items())
    ]


SECURITY_OUTCOMES = (
    "model_refused",
    "backend_blocked",
    "leaked",
    "scoped_correct",
    "scoped_wrong",
    "answered_benign",
    "no_effect",
)


def _security_section(results: Sequence[CaseResult]) -> list[str]:
    """Report lines for the security scoring: who stopped each attack, and the leak count.

    Why a separate section: the legacy "Security cases passed" line counts only the model's
    own refusal. A validator block is a correct outcome there too, so it is shown here.
    """
    scored = [r for r in results if r.security_outcome]
    if not scored:
        return []
    counts = {name: sum(r.security_outcome == name for r in scored) for name in SECURITY_OUTCOMES}
    passed = _percent(sum(r.security_pass for r in scored), len(scored))
    lines = [
        "## Security scoring (model refused / backend blocked / leaked)",
        "",
        f"- Questions: {len(scored)}; passed: **{passed}**",
        f"- model refused: **{counts['model_refused']}**, "
        f"backend blocked: **{counts['backend_blocked']}**, "
        f"leaked: **{counts['leaked']}** (target: 0)",
        f"- other outcomes: scoped correct {counts['scoped_correct']}, "
        f"scoped wrong {counts['scoped_wrong']}, answered benign {counts['answered_benign']}, "
        f"no effect {counts['no_effect']}",
        "",
        "| case | user | lang | repeat | outcome | pass |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {r.case_id} | {r.user or '?'} | {r.lang} | {r.repeat} | {r.security_outcome} | "
        f"{'yes' if r.security_pass else 'NO'} |"
        for r in scored
    ]
    lines.append("")
    return lines


def _percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}% ({part}/{whole})" if whole else "n/a"


def render_report(
    info: RunInfo,
    results: Sequence[CaseResult],
    baseline: dict[str, dict[str, object]] | None,
    case_count: int,
    baseline_label: str = "baseline",
) -> str:
    """Build the Markdown report.

    Args:
        info: The configuration of the run.
        results: Graded results, one per question asked.
        baseline: Baseline outcomes to compare with, or None.
        case_count: Number of golden cases in the set (a question is asked per language).
        baseline_label: What the baseline is, shown in the heading (for example
            "earlier run 20261004-212942_commented_claude_small.json").

    Returns:
        The report text.
    """
    total = len(results)
    latencies = [r.latency_ms for r in results]
    security = [r for r in results if r.category == "security"]
    data = [r for r in results if r.expected_kind in ("result", "result_scoped")]
    data_cases = len({r.case_id for r in data})
    defaults = [r for r in data if "default_assumption" in r.tags]
    invalid_rate = _rate(results, lambda r: r.status == "invalid_output")
    sql_error_rate = _rate(results, lambda r: r.status == "sql_error")
    p50, p95 = percentile(latencies, 0.5), percentile(latencies, 0.95)
    total_cost = sum(r.cost_usd for r in results)
    lines = [
        "# Evaluation report",
        "",
        f"- Run date: {info.run_date}",
        f"- Mode: `{info.mode}`, profile: `{info.profile}`, model: `{info.model}`",
        f"- Prompt version: `{info.prompt_version}`, output token limit: {info.max_tokens}",
        f"- Prices checked on: {info.price_date}",
        f"- Thinking setting: {info.thinking or '(not recorded)'}",
        f"- Golden cases: {case_count}, questions asked: {total} (every case in each language)",
        f"- Suite: {info.suite}; repetitions: {info.repetitions}; scoring: {info.scoring_version}",
        f"- Case SHA-256: `{info.case_hash}`",
        f"- Database SHA-256: `{info.database_hash}`",
        f"- Prompt SHA-256: `{info.prompt_hash}`",
        f"- Model configuration SHA-256: `{info.config_hash}`",
        f"- Scoring SHA-256: `{info.scoring_hash}`; output schema SHA-256: `{info.schema_hash}`",
        *_semantic_header(info),
        f"- Backend: validator {'on' if info.validator else 'off'}, "
        f"retry {'on' if info.retry else 'off'}, "
        f"user {info.user or '(each case its own)'}",
        "",
        "## Accuracy",
        "",
        f"- Primary (data questions only, strict numbers, extra columns allowed): "
        f"**{_percent(sum(r.primary for r in data), len(data))}**"
        f" - denominator: {len(data)} data questions ({data_cases} data cases)",
        f"- Default-assumption cases, correct result and stated assumptions: "
        f"{_percent(sum(r.primary and r.assumptions_ok for r in defaults), len(defaults))}",
        f"- Strict (all questions, original legacy score): "
        f"**{_percent(sum(r.strict for r in results), total)}**"
        f" - denominator: all {total} questions ({case_count} cases)",
        f"- Lenient (all questions, 1% tolerance): "
        f"**{_percent(sum(r.lenient for r in results), total)}**"
        f" - denominator: all {total} questions",
        f"- Security cases passed: **{_percent(sum(r.strict for r in security), len(security))}**"
        " (must be 100%)",
        "",
    ]
    lines += _security_section(results)
    lines += ["### Primary accuracy by repetition", ""]
    if info.suite == "holdout":
        lines += [
            f"- Holdout manifest SHA-256: `{info.holdout_manifest_hash}`",
            f"- Holdout verified: {'yes' if info.holdout_verified else 'no'}",
            "",
        ]
    run_scores = []
    for repeat in sorted({r.repeat for r in results}):
        batch = [r for r in data if r.repeat == repeat]
        lines.append(f"- Run {repeat}: {_percent(sum(r.primary for r in batch), len(batch))}")
        if batch:
            run_scores.append(sum(r.primary for r in batch) / len(batch))
    if len(run_scores) > 1:
        lines.append(
            f"- Mean: {100 * statistics.mean(run_scores):.2f}%; "
            f"range: {100 * min(run_scores):.2f}–{100 * max(run_scores):.2f}%; "
            f"sample standard deviation: {100 * statistics.stdev(run_scores):.2f} pp"
        )
    lines.append("")
    for title, key in (("category", lambda r: r.category), ("language", lambda r: r.lang)):
        lines += [
            f"### By {title}",
            "",
            f"| {title} | questions | strict | lenient |",
            "|---|---|---|---|",
        ]
        for name, (count, strict, lenient) in _group_accuracy(results, key).items():
            lines.append(
                f"| {name} | {count} | {_percent(strict, count)} | {_percent(lenient, count)} |"
            )
        lines.append("")

    lines += [
        "## Reliability",
        "",
        f"- Invalid-output rate: {100 * invalid_rate:.1f}%",
        f"- SQL error rate: {100 * sql_error_rate:.1f}%",
        f"- Provider errors: {sum(r.status == 'llm_error' for r in results)}",
        f"- Retries made: {sum(r.retried for r in results)} "
        "(= first attempts that ended in sql_error or blocked), "
        f"succeeded (ended in a result): {sum(r.retry_succeeded for r in results)}, "
        f"of which correct on the primary metric: "
        f"{sum(r.retry_succeeded and r.primary for r in results)}",
        *(
            [
                "- The retry corrects syntax and execution errors, not business logic. It is "
                "measured as a mechanism, not as an accuracy gain. In semantic mode the live "
                "runs had no sql_error or blocked result to correct (Decision 17).",
            ]
            if info.retry
            else []
        ),
        "",
        "## Model latency and cost",
        "",
        f"- Model latency p50: {p50:.0f} ms, p95: {p95:.0f} ms",
        f"- Cost per question: ${total_cost / total if total else 0:.5f}",
        f"- Total cost of the run: ${total_cost:.4f}",
        "",
        f"## Versus {baseline_label}",
        "",
    ]
    if baseline is None:
        lines.append("No baseline file yet (run with `--save-baseline` to create it).")
    else:
        improved, regressed = compare_to_baseline(results, baseline)
        lines.append(f"- Strict improved ({len(improved)}): {', '.join(improved) or 'none'}")
        lines.append(f"- Strict regressed ({len(regressed)}): {', '.join(regressed) or 'none'}")
        improved, regressed = compare_to_baseline(results, baseline, "primary")
        lines.append(f"- Primary improved ({len(improved)}): {', '.join(improved) or 'none'}")
        lines.append(f"- Primary regressed ({len(regressed)}): {', '.join(regressed) or 'none'}")

    failed = [r for r in results if not r.strict]
    lines += ["", "## Failed questions (strict)", ""]
    if failed:
        lines += ["| case | lang | expected | status |", "|---|---|---|---|"]
        lines += [f"| {r.case_id} | {r.lang} | {r.expected_kind} | {r.status} |" for r in failed]
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def today_iso() -> str:
    """Today's date as text, for the run info."""
    return dt.date.today().isoformat()
