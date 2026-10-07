"""Fingerprint evaluation inputs and enforce human review before release.

This evaluation-only module prevents a changed case set from silently reusing an
old baseline. A hash proves content identity, not authorship or external timing.
"""

import ast
import hashlib
import json
import textwrap
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


def source_fingerprint(sources: Sequence[str]) -> str:
    """Hash Python source code by its syntax tree, not by its text.

    Why: the scoring hash must change when scoring LOGIC changes and stay the same when
    only formatting, comments or line endings change (a Windows checkout has CRLF, a Linux
    one LF). Parsing into a syntax tree and hashing its dump removes exactly those
    differences. A docstring is part of the tree, so editing one counts as a change; that
    errs on the safe side.

    Args:
        sources: Python source text of each scoring function or module, in a fixed order.

    Returns:
        A SHA-256 hex digest.
    """
    digest = hashlib.sha256()
    for source in sources:
        digest.update(ast.dump(ast.parse(textwrap.dedent(source))).encode())
        digest.update(b"|")  # separator, so moving code between two sources changes the hash
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


def _canonical_crlf_hash(path: Path) -> str:
    """SHA-256 of the file after rewriting every line ending to CRLF.

    The two replace calls make the result independent of the starting form: the first
    turns every CRLF into LF, the second turns every LF into exactly one CRLF.
    """
    content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return hashlib.sha256(content).hexdigest()


def matches_recorded_hash(path: Path, recorded: str | None) -> str | None:
    """Compare a file with a hash recorded at freeze time, tolerating line endings.

    Why: the frozen manifests were written on a Windows checkout (CRLF files), while git
    stores and checks out LF. The recorded byte hashes can therefore never match a fresh
    clone, although the content is identical (Decision 21).

    Design note: the raw bytes are compared first and the canonical CRLF form only if that
    fails, so an unchanged checkout is always judged on bytes alone. Any difference beyond
    line endings still fails. Only the frozen development suite uses this; the holdout
    commitment stays strictly byte-based (`holdout_commitment.py`).

    Args:
        path: The file to check.
        recorded: The SHA-256 hex digest stored in the manifest.

    Returns:
        "bytes" for a raw match, "line-endings" for a match after normalization, None if
        the file differs.
    """
    if recorded is None:
        return None
    if file_hash(path) == recorded:
        return "bytes"
    if _canonical_crlf_hash(path) == recorded:
        return "line-endings"
    return None


def require_frozen(directory: Path, cases: Sequence[GoldenCase], db_path: Path) -> list[str]:
    """Verify that a reviewed suite and its database match the release manifest.

    Returns:
        The names of files that matched only after line-ending normalization (empty on a
        checkout whose bytes equal the frozen ones).

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
    normalized: list[str] = []
    recorded_files = manifest.get("files", {})
    yaml_paths = sorted(directory.glob("*.yaml"))
    if sorted(recorded_files) != [p.name for p in yaml_paths]:
        raise ValueError("Frozen YAML files have changed")
    checks = [(p, recorded_files[p.name], "Frozen YAML files have changed") for p in yaml_paths]
    checks.append(
        (
            directory / "oracles.py",
            manifest["oracle_hash"],
            "Independent reference calculations changed after freezing",
        )
    )
    legacy = directory / "legacy_oracles.py"
    if legacy.exists():
        checks.append(
            (
                legacy,
                manifest["legacy_oracle_hash"],
                "Legacy independent calculations changed after freezing",
            )
        )
    checks.append(
        (
            Path(__file__).parent / "reference_tools.py",
            manifest["reference_tools_hash"],
            "Independent calculation helpers changed after freezing",
        )
    )
    for path, recorded, message in checks:
        outcome = matches_recorded_hash(path, recorded)
        if outcome is None:
            raise ValueError(message)
        if outcome == "line-endings":
            normalized.append(path.name)
    return normalized
