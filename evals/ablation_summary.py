"""Summary table of the semantic ablation runs (Decision 23).

What it does: reads several run files written by `evals.run_eval` and prints one Markdown
row per run: suite, ablation variant, primary accuracy (overall and per repetition), how
often the model asked back on clarification cases, how often it asked back needlessly on
data cases, and the cost.

Why it exists: the ablation produces eight run files (four variants on two suites). Each
has its own report, but the README needs the numbers side by side, computed the same way.
The paired differences come from `evals.paired_analysis`, which also checks that the runs
are comparable; this script only counts.

Where it sits in the pipeline: evaluation only (after the runs, before the write-up).

Usage:
    uv run python -m evals.ablation_summary RUN.json [RUN.json ...]
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from evals.report import CaseResult

app = typer.Typer(add_completion=False, help="Side-by-side table of ablation runs.")


@dataclass(frozen=True)
class RunSummary:
    """The counted numbers of one run file.

    Attributes:
        suite: "development" or "holdout".
        ablation: The semantic ablation variant ("full" for files without the key).
        primary: Correct data questions (primary score) and the number of data questions.
        per_repeat: Primary accuracy (0-1) of each repetition, in repetition order.
        asked: Clarification cases where the model asked back, and their number.
        needless: Data cases where the model asked back, and their number.
        cost_usd: Total model cost of the run.
    """

    suite: str
    ablation: str
    primary: tuple[int, int]
    per_repeat: list[float]
    asked: tuple[int, int]
    needless: tuple[int, int]
    cost_usd: float


def summarize(info: dict[str, object], results: list[CaseResult]) -> RunSummary:
    """Count the numbers of one run.

    Args:
        info: The `info` object of the run file.
        results: All graded questions of the run.

    Returns:
        The summary. "Asked back" means the pipeline status is "clarification", the same
        definition as the "Clarification behaviour" section of the run report.
    """
    data = [r for r in results if r.expected_kind in ("result", "result_scoped")]
    should_ask = [r for r in results if r.expected_kind == "clarification"]
    per_repeat = []
    for repeat in sorted({r.repeat for r in data}):
        batch = [r for r in data if r.repeat == repeat]
        per_repeat.append(sum(r.primary for r in batch) / len(batch))
    return RunSummary(
        suite=str(info.get("suite", "")),
        ablation=str(info.get("ablation", "full")),
        primary=(sum(r.primary for r in data), len(data)),
        per_repeat=per_repeat,
        asked=(sum(r.status == "clarification" for r in should_ask), len(should_ask)),
        needless=(sum(r.status == "clarification" for r in data), len(data)),
        cost_usd=sum(r.cost_usd for r in results),
    )


def _share(counts: tuple[int, int]) -> str:
    part, whole = counts
    return f"{100 * part / whole:.1f}% ({part}/{whole})" if whole else "n/a"


def render_table(summaries: list[RunSummary]) -> str:
    """Render the summaries as one Markdown table, in the order given."""
    lines = [
        "| suite | ablation | primary | per repetition | asked back (clarification cases) "
        "| asked back needlessly (data cases) | cost USD |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        repeats = " / ".join(f"{100 * value:.1f}" for value in s.per_repeat)
        lines.append(
            f"| {s.suite} | {s.ablation} | {_share(s.primary)} | {repeats} | {_share(s.asked)} "
            f"| {_share(s.needless)} | {s.cost_usd:.2f} |"
        )
    return "\n".join(lines) + "\n"


@app.command()
def main(
    run_files: Annotated[list[Path], typer.Argument(help="run JSON files written by run_eval")],
) -> None:
    """Print the side-by-side table of the given run files."""
    summaries = []
    for path in run_files:
        document = json.loads(path.read_text(encoding="utf-8"))
        results = [CaseResult(**row) for row in document["results"]]
        summaries.append(summarize(document["info"], results))
    typer.echo(render_table(summaries))


if __name__ == "__main__":
    app()
