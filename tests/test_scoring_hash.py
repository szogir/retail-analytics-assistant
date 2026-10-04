"""The scoring hash must follow the grading logic, not the command-line wiring."""

from pathlib import Path

import pytest

from evals import run_eval
from evals.provenance import source_fingerprint
from retail_assistant.pipeline import Answer


def test_fingerprint_ignores_comments_whitespace_and_line_endings() -> None:
    plain = "def f(x):\n    return x + 1\n"
    decorated = "def f( x ):\r\n    # a comment\r\n    return  x+1\r\n"
    assert source_fingerprint([plain]) == source_fingerprint([decorated])


def test_fingerprint_changes_with_logic_and_order() -> None:
    assert source_fingerprint(["def f(x):\n    return x + 1\n"]) != source_fingerprint(
        ["def f(x):\n    return x + 2\n"]
    )
    assert source_fingerprint(["a = 1", "b = 2"]) != source_fingerprint(["b = 2", "a = 1"])
    # The same code split differently between sources is not the same fingerprint.
    assert source_fingerprint(["a = 1", "b = 2"]) != source_fingerprint(["a = 1\nb = 2"])


def test_changing_a_grading_function_changes_the_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    before = run_eval.scoring_hash()

    def grade_everything_right(*args: object) -> tuple[bool, bool]:
        return True, True

    monkeypatch.setattr(run_eval, "grade", grade_everything_right)
    assert run_eval.scoring_hash() != before


def test_changing_the_comparison_module_changes_the_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before = run_eval.scoring_hash()
    original = (run_eval.EVALS_DIR / "compare.py").read_text(encoding="utf-8")
    (tmp_path / "compare.py").write_text(
        original.replace("STRICT_REL_TOL = 1e-6", "STRICT_REL_TOL = 1e-3"), encoding="utf-8"
    )
    monkeypatch.setattr(run_eval, "EVALS_DIR", tmp_path)
    assert run_eval.scoring_hash() != before


def test_changing_the_command_line_wiring_does_not_change_the_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = run_eval.scoring_hash()

    def different_main() -> None:
        print("a new option, a new message")

    def different_run_evaluation() -> list[Answer]:
        return []

    monkeypatch.setattr(run_eval, "main", different_main)
    monkeypatch.setattr(run_eval, "run_evaluation", different_run_evaluation)
    assert run_eval.scoring_hash() == before
