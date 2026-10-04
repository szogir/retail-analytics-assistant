"""Commit external benchmark content by hash without publishing its questions.

The public manifest contains only digests and aggregate metadata. Evaluation must
verify it before using sealed data; publication of exact case bytes later makes
the commitment independently checkable. This is not proof of author blindness.
"""

import datetime as dt
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evals.golden import load_golden_set
from evals.provenance import file_hash, require_reviewed

MANIFEST_PATH = Path(__file__).resolve().parent / "holdout_manifest.json"


class HoldoutManifest(BaseModel):
    """The complete allowlist of public commitment fields; case content is forbidden."""

    model_config = ConfigDict(extra="forbid")

    files: dict[str, str]
    suite_hash: str
    case_count: int = Field(gt=0)
    category_counts: dict[str, int]
    expected_kind_counts: dict[str, int]
    schema_version: Literal["holdout_v1"] = "holdout_v1"
    data_generator_identity: str
    freeze_date: dt.datetime

    @model_validator(mode="after")
    def _consistent_counts(self) -> "HoldoutManifest":
        """Reject malformed aggregate metadata before it can be treated as proof."""
        if sum(self.category_counts.values()) != self.case_count:
            raise ValueError("Category counts must sum to case_count")
        if sum(self.expected_kind_counts.values()) != self.case_count:
            raise ValueError("Expected-kind counts must sum to case_count")
        if self.freeze_date.tzinfo is None:
            raise ValueError("freeze_date must include a timezone")
        if any(not re.fullmatch(r"[0-9]{3}_case\.yaml|oracles\.py", name) for name in self.files):
            raise ValueError("Holdout commitment filenames must remain opaque")
        if sum(name.endswith(".yaml") for name in self.files) != self.case_count:
            raise ValueError("Committed YAML count must match case_count")
        return self


def build_commitment(directory: Path, db_path: Path, freeze_date: dt.datetime) -> HoldoutManifest:
    """Fingerprint reviewed cases and their independent calculator.

    Args:
        directory: The owner's external suite directory.
        db_path: The exact validated database file.
        freeze_date: An explicit timezone-aware timestamp, retained during verification.

    Returns:
        An allowlisted manifest without question text, SQL, notes or results.

    Raises:
        ValueError: If personal approval is incomplete.
        FileNotFoundError: If cases, calculator or database are missing.
    """
    cases = load_golden_set(directory)
    require_reviewed(cases)
    paths = [*sorted(directory.glob("*.yaml")), directory / "oracles.py"]
    files = {path.name: file_hash(path) for path in paths}
    combined = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return HoldoutManifest(
        files=files,
        suite_hash=hashlib.sha256(combined).hexdigest(),
        case_count=len(cases),
        category_counts=dict(sorted(Counter(c.category for c in cases).items())),
        expected_kind_counts=dict(sorted(Counter(c.expected.kind for c in cases).items())),
        data_generator_identity=f"sha256:{file_hash(db_path)}",
        freeze_date=freeze_date,
    )


def write_commitment(directory: Path, db_path: Path, manifest_path: Path = MANIFEST_PATH) -> str:
    """Write an immutable commitment after the caller has validated references.

    Args:
        directory: The reviewed external suite.
        db_path: The database used by the independent reference check.
        manifest_path: Public destination, overridable for synthetic unit tests.

    Returns:
        SHA-256 of the exact public manifest bytes.

    Raises:
        FileExistsError: If a commitment already exists; no silent replacement is allowed.
        ValueError: If any case is unreviewed.
    """
    manifest = build_commitment(directory, db_path, dt.datetime.now(dt.UTC))
    # Explicit LF preserves the manifest digest across Windows and Git checkouts.
    with manifest_path.open("x", encoding="utf-8", newline="\n") as target:
        target.write(manifest.model_dump_json(indent=2) + "\n")
    return file_hash(manifest_path)


def verify_commitment(directory: Path, db_path: Path, manifest_path: Path = MANIFEST_PATH) -> str:
    """Verify every committed file, aggregate count and database identity.

    Args:
        directory: The configured external suite, never inferred from the manifest.
        db_path: The intended evaluation database.
        manifest_path: The public hash commitment.

    Returns:
        Manifest SHA-256 only after successful verification.

    Raises:
        FileNotFoundError: If the owner has not frozen the holdout or an input is missing.
        ValueError: If approval, case bytes, calculator, counts or database differ.
    """
    if not manifest_path.is_file():
        raise FileNotFoundError("Holdout manifest missing: complete personal review, then --freeze")
    recorded = HoldoutManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    actual = build_commitment(directory, db_path, recorded.freeze_date)
    if actual != recorded:
        raise ValueError("Holdout commitment mismatch; do not evaluate modified sealed data")
    return file_hash(manifest_path)
