"""Exercise public hash commitments using invented temporary cases, never the real holdout."""

import json
from pathlib import Path

import pytest
import yaml

from evals.holdout_commitment import verify_commitment, write_commitment
from evals.provenance import file_hash
from evals.report import RunInfo, render_report


@pytest.fixture
def invented_suite(tmp_path: Path) -> tuple[Path, Path, Path]:
    """One intentionally artificial reviewed case and a fake database identity."""
    private = tmp_path / "private"
    private.mkdir()
    data = {
        "id": "901",
        "questions": {"en": "Invented fixture question?", "hu": "Fixture text?"},
        "user": "carla",
        "as_of_date": "2026-10-04",
        "category": "aggregation",
        "traps": [],
        "expected": {"kind": "result"},
        "reference_sql": "SELECT 4321 AS fixture_value",
        "notes": "Private fixture note that must not appear in a public manifest.",
        "reviewed": True,
        "reviewed_on": "2026-10-04",
        "reviewed_by": "Fixture reviewer",
    }
    (private / "901_case.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    (private / "oracles.py").write_text("# Synthetic fixture calculator\n", encoding="utf-8")
    database = tmp_path / "fixture.db"
    database.write_bytes(b"invented database bytes")
    return private, database, tmp_path / "manifest.json"


def test_freeze_writes_only_allowlisted_metadata_and_verifies(
    invented_suite: tuple[Path, Path, Path],
) -> None:
    private, database, manifest = invented_suite
    digest = write_commitment(private, database, manifest)
    assert digest == file_hash(manifest) == verify_commitment(private, database, manifest)
    text = manifest.read_text(encoding="utf-8")
    assert not any(secret in text for secret in ("Invented fixture", "SELECT", "Private fixture"))
    assert set(json.loads(text)) == {
        "files",
        "suite_hash",
        "case_count",
        "category_counts",
        "expected_kind_counts",
        "schema_version",
        "data_generator_identity",
        "freeze_date",
    }
    with pytest.raises(FileExistsError):
        write_commitment(private, database, manifest)


@pytest.mark.parametrize("field,value", [("reviewed", False), ("reviewed_on", None)])
def test_freeze_refuses_missing_personal_approval(
    invented_suite: tuple[Path, Path, Path], field: str, value: object
) -> None:
    private, database, manifest = invented_suite
    case_file = private / "901_case.yaml"
    case = yaml.safe_load(case_file.read_text())
    case[field] = value
    if field == "reviewed":
        case.update(reviewed_on=None, reviewed_by=None)
    case_file.write_text(yaml.safe_dump(case), encoding="utf-8")
    with pytest.raises(ValueError):
        write_commitment(private, database, manifest)
    assert not manifest.exists()


@pytest.mark.parametrize(
    "target", ["question", "sql", "notes", "calculator", "database", "added", "removed"]
)
def test_verify_rejects_changed_or_missing_inputs(
    invented_suite: tuple[Path, Path, Path], target: str
) -> None:
    private, database, manifest = invented_suite
    write_commitment(private, database, manifest)
    case_file = private / "901_case.yaml"
    if target in ("question", "sql", "notes"):
        case = yaml.safe_load(case_file.read_text())
        if target == "question":
            case["questions"]["en"] = "A changed fixture question"
        else:
            case["reference_sql" if target == "sql" else "notes"] = "Changed content"
        case_file.write_text(yaml.safe_dump(case), encoding="utf-8")
    elif target == "calculator":
        (private / "oracles.py").write_text("# Changed calculator\n")
    elif target == "database":
        database.write_bytes(b"changed database bytes")
    elif target == "added":
        case = yaml.safe_load(case_file.read_text())
        case["id"] = "902"
        (private / "902_case.yaml").write_text(yaml.safe_dump(case), encoding="utf-8")
    else:
        case_file.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        verify_commitment(private, database, manifest)


def test_manifest_rejects_extra_content_fields(invented_suite: tuple[Path, Path, Path]) -> None:
    private, database, manifest = invented_suite
    write_commitment(private, database, manifest)
    content = json.loads(manifest.read_text())
    content["notes"] = "This field must never become public"
    manifest.write_text(json.dumps(content))
    with pytest.raises(ValueError):
        verify_commitment(private, database, manifest)


@pytest.mark.parametrize("verified,label", [(True, "yes"), (False, "no")])
def test_report_prints_manifest_digest_and_verification_state(verified: bool, label: str) -> None:
    info = RunInfo(
        "naive",
        "p",
        "m",
        "v",
        "2026-10-04",
        "2026-10-04",
        4096,
        suite="holdout",
        holdout_manifest_hash="abc123",
        holdout_verified=verified,
    )
    text = render_report(info, [], None, 0)
    assert "abc123" in text
    assert f"Holdout verified: {label}" in text


def test_holdout_verification_stays_byte_strict(invented_suite: tuple[Path, Path, Path]) -> None:
    """A line-ending change must fail the holdout check: only the development suite is tolerant."""
    private, database, manifest = invented_suite
    case_file = private / "901_case.yaml"
    case_file.write_bytes(case_file.read_bytes().replace(b"\n", b"\r\n"))
    write_commitment(private, database, manifest)
    verify_commitment(private, database, manifest)  # identical bytes pass
    case_file.write_bytes(case_file.read_bytes().replace(b"\r\n", b"\n"))
    with pytest.raises(ValueError, match="mismatch"):
        verify_commitment(private, database, manifest)
