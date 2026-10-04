"""Verify reference answers, prepare human review, and freeze approved suites.

This offline release gate never calls a model. It keeps holdout questions, oracle
code and detailed output inside the selected suite, outside ordinary development.
"""

import argparse
import datetime as dt
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

from evals.compare import tables_match
from evals.golden import GoldenCase, load_golden_set
from evals.provenance import case_hash, file_hash, require_reviewed
from evals.reference_tools import ReferenceData
from evals.suites import suite_directory
from retail_assistant.sql.executor import execute_query

Oracle = Callable[[str, ReferenceData], list[tuple[object, ...]]]
ROOT = Path(__file__).resolve().parents[1]


def load_oracle(path: Path) -> Oracle:
    """Load the explicitly selected suite's independent calculation module.

    Raises:
        ValueError: If the selected module cannot be loaded.
    """
    spec = importlib.util.spec_from_file_location("suite_oracle", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load oracle: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(Oracle, module.expected)


def verify_references(directory: Path, db_path: Path) -> dict[str, object]:
    """Execute all SQL references and require independently equal DataFrame results.

    Args:
        directory: A development or sealed evaluation directory.
        db_path: The exact database to validate and fingerprint.

    Returns:
        Candidate manifest, explicitly pending human approval.

    Raises:
        ValueError: On a missing oracle, result mismatch or invalid expected shape.
    """
    cases = load_golden_set(directory)
    validate_composition(cases)
    artifacts = directory / "artifacts"
    data = ReferenceData(db_path, artifacts / "frames")
    oracle = load_oracle(directory / "oracles.py")
    legacy_path = directory / "legacy_oracles.py"
    legacy = load_oracle(legacy_path) if legacy_path.exists() else None
    checks: list[str] = []
    review = [
        "# Human review worksheet",
        "",
        "Status: pending personal approval.",
        "",
        "For every case check both languages, scope, dates, metric conventions, SQL,",
        "independent arithmetic and expected result. Automated agreement does not",
        "prove that both implementations express the intended business question.",
        "",
    ]
    for case in cases:
        review += [
            f"## {case.id}",
            "",
            f"- EN: {case.questions.en}",
            f"- HU: {case.questions.hu}",
            f"- Expected: {case.expected.kind}",
            f"- Notes: {case.notes}",
            f"- Tags: {', '.join(case.tags) or 'none'}",
            f"- Reviewed: {case.reviewed}; date: {case.reviewed_on}",
            "",
        ]
        if case.reference_sql:
            result = execute_query(db_path, case.reference_sql)
            compute = legacy if legacy is not None and int(case.id) <= 21 else oracle
            expected = compute(case.id, data)
            if result.truncated or not tables_match(
                expected, result.rows, case.order_sensitive, 1e-9, False
            ):
                raise ValueError(f"Independent reference mismatch: {case.id}")
            check_shape(case, result.rows)
            checks.append(case.id)
            review += [
                "```sql",
                case.reference_sql.strip(),
                "```",
                "",
                f"Independent result: `{result.rows!r}`",
                "",
            ]
        if case.assumption_patterns:
            review += [f"Assumption topic checks: `{case.assumption_patterns!r}`", ""]
        review += [
            "- [ ] Personally checked; set reviewed, reviewed_on and reviewed_by in YAML.",
            "",
        ]
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "review.md").write_text("\n".join(review), encoding="utf-8")
    manifest: dict[str, object] = {
        "status": "candidate_pending_human_review",
        "case_count": len(cases),
        "case_hash": case_hash(cases),
        "files": {p.name: file_hash(p) for p in sorted(directory.glob("*.yaml"))},
        "database_hash": file_hash(db_path),
        "reference_cases_checked": checks,
        "oracle_hash": file_hash(directory / "oracles.py"),
        "legacy_oracle_hash": file_hash(legacy_path) if legacy_path.exists() else None,
        "reference_tools_hash": file_hash(ROOT / "evals" / "reference_tools.py"),
        "validated_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    (directory / "candidate.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def check_shape(case: GoldenCase, rows: list[tuple[object, ...]]) -> None:
    """Require explicitly declared empty, NULL or ordinary reference output."""
    if case.answer_shape == "empty":
        valid = not rows
    elif case.answer_shape == "null":
        valid = bool(rows) and all(v is None for row in rows for v in row)
    else:
        valid = bool(rows) and any(v is not None for row in rows for v in row)
    if not valid:
        raise ValueError(f"Unexpected reference result shape: {case.id}")


def validate_composition(cases: list[GoldenCase]) -> None:
    """Reject an incomplete or accidentally rebalanced version-one suite.

    Raises:
        ValueError: If any preregistered count or bilingual question is missing.
    """
    counts = (
        len(cases),
        sum(c.expected.kind == "result" for c in cases),
        sum(c.expected.kind == "clarification" for c in cases),
        sum(c.category == "security" and c.expected.kind == "refusal" for c in cases),
        sum(c.category == "out_of_scope" and c.expected.kind == "refusal" for c in cases),
        sum("default_assumption" in c.tags for c in cases),
    )
    if counts != (50, 40, 5, 4, 1, 10):
        raise ValueError(f"Suite composition differs from the registered plan: {counts}")
    if any(not c.questions.en.strip() or not (c.questions.hu or "").strip() for c in cases):
        raise ValueError("Both languages are required for every release case")


def main() -> None:
    """Validate offline, or freeze only after all human reviews are recorded."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["development", "holdout"], required=True)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "retail.duckdb")
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--holdout-dir", type=Path, help="External holdout path (or HOLDOUT_DIR)")
    args = parser.parse_args()
    try:
        directory = suite_directory(args.suite, args.holdout_dir)
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))
    if args.freeze:
        require_reviewed(load_golden_set(directory))
        if (directory / "frozen.json").exists():
            raise ValueError(
                "Already frozen; explicitly version any correction instead of overwriting"
            )
    manifest = verify_references(directory, args.db)
    if args.freeze:
        manifest["status"] = "frozen"
        manifest["frozen_at"] = dt.datetime.now(dt.UTC).isoformat()
        with (directory / "frozen.json").open("x", encoding="utf-8") as target:
            target.write(json.dumps(manifest, indent=2) + "\n")
    print(f"{args.suite}: {manifest['case_count']} cases; status={manifest['status']}")


if __name__ == "__main__":
    main()
