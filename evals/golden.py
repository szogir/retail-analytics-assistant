"""Golden set: typed model and loader for the evaluation test cases.

What it does: reads `evals/golden_set/*.yaml` and validates every file against a Pydantic
model, so a typo in a case fails loudly instead of silently skewing the accuracy number.

Why it exists: the golden set is the yardstick of the whole project. Each case has a
question, the user who asks it, a fixed "today" (`as_of_date`) and a reference SQL whose
RESULT (not text) is the correct answer.

Where it sits in the pipeline: evaluation only (the eval runner loads the cases, runs
the assistant and compares result tables with the reference SQL result).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

GOLDEN_SET_DIR = Path(__file__).parent / "golden_set"


class Questions(BaseModel):
    """The same question in both languages.

    `hu` is optional only until the Hungarian translations are written; the evaluation
    of the Hungarian questions skips cases where it is missing.
    """

    model_config = ConfigDict(extra="forbid")

    en: str
    hu: str | None = None


class Expected(BaseModel):
    """What a correct answer looks like."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["result", "clarification", "refusal", "result_scoped"]


class GoldenCase(BaseModel):
    """One evaluation case.

    Attributes:
        id: Unique identifier, also the file name prefix.
        questions: The question in English and Hungarian.
        user: Who asks (decides which stores they may see).
        as_of_date: The fixed "today" for relative expressions such as "last month".
            Why fixed: the answer must not change when the tests run on a different day.
        category: Kind of question (aggregation, ratio, time, ranking, reference).
        traps: Which built-in data traps the question touches (1-5, see data_gen.facts).
        expected: The expected answer kind.
        reference_sql: SQL whose result is the correct answer.
        order_sensitive: True if the row order is part of the answer (rankings).
        notes: Why the case exists and how the answer is defined.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    questions: Questions
    user: str
    as_of_date: dt.date
    category: str
    traps: list[int | str]
    expected: Expected
    reference_sql: str
    order_sensitive: bool = False
    notes: str = ""


def load_golden_set(directory: Path = GOLDEN_SET_DIR) -> list[GoldenCase]:
    """Load and validate all golden cases.

    Args:
        directory: Folder with one YAML file per case.

    Returns:
        The cases, sorted by id.

    Raises:
        pydantic.ValidationError: If a file does not match the model.
        ValueError: If two files use the same case id.
    """
    cases: list[GoldenCase] = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        cases.append(GoldenCase.model_validate(raw))

    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids in the golden set")
    return sorted(cases, key=lambda case: case.id)
