"""Fingerprint evaluation inputs and enforce human review before release.

This evaluation-only module prevents a changed case set from silently reusing an
old baseline. A hash proves content identity, not authorship or external timing.
"""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from evals.golden import GoldenCase


def file_hash(path: Path) -> str:
    """Return a streaming SHA-256 fingerprint of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def case_hash(cases: Sequence[GoldenCase]) -> str:
    """Hash all validated case content, independently of YAML whitespace.

    Args:
        cases: The exact selected cases, including questions, SQL and review metadata.

    Returns:
        A SHA-256 hex digest, stable across file ordering.
    """
    payload = [case.model_dump(mode="json") for case in sorted(cases, key=lambda c: c.id)]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def require_reviewed(cases: Sequence[GoldenCase]) -> None:
    """Reject a release or live run until every case has human approval.

    Raises:
        ValueError: If any case is still awaiting human review.
    """
    pending = [case.id for case in cases if not case.reviewed]
    if pending:
        raise ValueError(f"Human review required for {len(pending)} cases: {', '.join(pending)}")


def require_frozen(directory: Path, cases: Sequence[GoldenCase], db_path: Path) -> None:
    """Verify that a reviewed suite and its database match the release manifest.

    Raises:
        FileNotFoundError: If the suite has not been frozen.
        ValueError: If approval or any recorded input differs.
    """
    require_reviewed(cases)
    manifest = json.loads((directory / "frozen.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "frozen":
        raise ValueError("A candidate manifest is not a frozen release")
    expected_ids = [c.id for c in cases if c.expected.kind in ("result", "result_scoped")]
    if manifest.get("reference_cases_checked") != expected_ids:
        raise ValueError("Not every result case has an independent reference check")
    if manifest["case_hash"] != case_hash(cases) or manifest["case_count"] != len(cases):
        raise ValueError("Frozen case content has changed; release a new version")
    if manifest["database_hash"] != file_hash(db_path):
        raise ValueError("Database differs from the frozen reference validation")
    if manifest.get("files") != {p.name: file_hash(p) for p in sorted(directory.glob("*.yaml"))}:
        raise ValueError("Frozen YAML files have changed")
    if manifest["oracle_hash"] != file_hash(directory / "oracles.py"):
        raise ValueError("Independent reference calculations changed after freezing")
    legacy = directory / "legacy_oracles.py"
    if legacy.exists() and manifest["legacy_oracle_hash"] != file_hash(legacy):
        raise ValueError("Legacy independent calculations changed after freezing")
    if manifest["reference_tools_hash"] != file_hash(Path(__file__).parent / "reference_tools.py"):
        raise ValueError("Independent calculation helpers changed after freezing")
