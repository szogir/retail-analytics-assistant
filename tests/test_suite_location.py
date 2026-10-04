"""Test external suite configuration with invented fixture paths, never real holdout data."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from evals import suites
from evals.golden import load_golden_set
from evals.run_eval import app


def test_holdout_location_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOLDOUT_DIR", raising=False)
    with pytest.raises(ValueError, match="HOLDOUT_DIR or pass --holdout-dir"):
        suites.suite_directory("holdout")
    result = CliRunner().invoke(app, ["--suite", "holdout"])
    assert result.exit_code == 2
    assert "Holdout location missing" in result.output


def test_explicit_path_overrides_environment_and_must_be_external(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    external = tmp_path / "private"
    external.mkdir()
    monkeypatch.setattr(suites, "PROJECT_ROOT", repo)
    monkeypatch.setenv("HOLDOUT_DIR", str(tmp_path / "missing"))
    assert suites.suite_directory("holdout", external) == external
    with pytest.raises(FileNotFoundError):
        suites.suite_directory("holdout")
    monkeypatch.setenv("HOLDOUT_DIR", str(repo))
    with pytest.raises(ValueError, match="outside"):
        suites.suite_directory("holdout")
    with pytest.raises(FileNotFoundError, match="no .* case files"):
        load_golden_set(external)


def test_development_never_reads_holdout_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object) -> None:
        raise AssertionError("Development must not consult HOLDOUT_DIR")

    monkeypatch.setattr(suites, "os", SimpleNamespace(environ=SimpleNamespace(get=forbidden)))
    assert suites.suite_directory("development").name == "golden_set"
