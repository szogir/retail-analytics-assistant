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
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path


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

    @property
    def key(self) -> str:
        """Identifier used in the baseline file, e.g. ``004:hu``."""
        return f"{self.case_id}:{self.lang}"


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
    results: Sequence[CaseResult], baseline: dict[str, dict[str, object]]
) -> tuple[list[str], list[str]]:
    """List the cases that got better or worse than in the baseline (strict outcome).

    Args:
        results: The current run.
        baseline: The `results` object of the baseline file, keyed like ``004:hu``.

    Returns:
        (improved keys, regressed keys). Cases that are not in the baseline are ignored.
    """
    improved: list[str] = []
    regressed: list[str] = []
    for result in results:
        before = baseline.get(result.key)
        if before is None:
            continue
        if result.strict and not before["strict"]:
            improved.append(result.key)
        elif before["strict"] and not result.strict:
            regressed.append(result.key)
    return improved, regressed


def save_baseline(path: Path, info: RunInfo, results: Sequence[CaseResult]) -> None:
    """Write the per-case outcomes of a run as the new baseline (versioned in git)."""
    document = {
        "info": asdict(info),
        "case_count": len(results),
        "results": {
            r.key: {"strict": r.strict, "lenient": r.lenient, "status": r.status} for r in results
        },
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_baseline(path: Path) -> dict[str, dict[str, object]] | None:
    """Read the `results` object of the baseline file, or None if there is no baseline yet."""
    if not path.is_file():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
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
        "",
        "## Accuracy",
        "",
        f"- Strict: **{_percent(sum(r.strict for r in results), total)}**",
        f"- Lenient: **{_percent(sum(r.lenient for r in results), total)}**",
        f"- Security cases passed: **{_percent(sum(r.strict for r in security), len(security))}**"
        " (must be 100%)",
        "",
    ]
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
        lines.append(f"- Improved ({len(improved)}): {', '.join(improved) or 'none'}")
        lines.append(f"- Regressed ({len(regressed)}): {', '.join(regressed) or 'none'}")

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
