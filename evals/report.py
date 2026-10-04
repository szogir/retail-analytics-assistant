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


def load_baseline(path: Path, info: RunInfo | None = None) -> dict[str, dict[str, object]] | None:
    """Read the `results` object of the baseline file, or None if there is no baseline yet."""
    if not path.is_file():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    if info is not None:
        for key in (
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
        ):
            if document["info"].get(key) != getattr(info, key):
                raise ValueError(f"Incompatible baseline: {key}")
    results: dict[str, dict[str, object]] = document["results"]
    return results


def _percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}% ({part}/{whole})" if whole else "n/a"


def render_report(
    info: RunInfo,
    results: Sequence[CaseResult],
    baseline: dict[str, dict[str, object]] | None,
    case_count: int,
) -> str:
    """Build the Markdown report.

    Args:
        info: The configuration of the run.
        results: Graded results, one per question asked.
        baseline: Baseline outcomes to compare with, or None.
        case_count: Number of golden cases in the set (a question is asked per language).

    Returns:
        The report text.
    """
    total = len(results)
    latencies = [r.latency_ms for r in results]
    security = [r for r in results if r.category == "security"]
    data = [r for r in results if r.expected_kind in ("result", "result_scoped")]
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
        f"- Golden cases: {case_count}, questions asked: {total} (every case in each language)",
        f"- Suite: {info.suite}; repetitions: {info.repetitions}; scoring: {info.scoring_version}",
        f"- Case SHA-256: `{info.case_hash}`",
        f"- Database SHA-256: `{info.database_hash}`",
        f"- Prompt SHA-256: `{info.prompt_hash}`",
        f"- Model configuration SHA-256: `{info.config_hash}`",
        f"- Scoring SHA-256: `{info.scoring_hash}`; output schema SHA-256: `{info.schema_hash}`",
        "",
        "## Accuracy",
        "",
        f"- Primary (data only, strict numbers, extra columns allowed): "
        f"**{_percent(sum(r.primary for r in data), len(data))}**",
        f"- Default-assumption cases, correct result and stated assumptions: "
        f"{_percent(sum(r.primary and r.assumptions_ok for r in defaults), len(defaults))}",
        f"- Strict: **{_percent(sum(r.strict for r in results), total)}**",
        f"- Lenient: **{_percent(sum(r.lenient for r in results), total)}**",
        f"- Security cases passed: **{_percent(sum(r.strict for r in security), len(security))}**"
        " (must be 100%)",
        "",
    ]
    lines += ["### Primary accuracy by repetition", ""]
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
        "",
        "## Latency and cost",
        "",
        f"- Latency p50: {p50:.0f} ms, p95: {p95:.0f} ms",
        f"- Cost per question: ${total_cost / total if total else 0:.5f}",
        f"- Total cost of the run: ${total_cost:.4f}",
        "",
        "## Versus baseline",
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
