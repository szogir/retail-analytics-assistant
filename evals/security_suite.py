"""Security suite: typed model and loader for the backend-protection cases.

What it does: reads `evals/security_suite/*.yaml`. A security case is a golden case plus three
fields that only make sense for security: what kind of attack it is, which result would be a
LEAK (the unscoped answer a restricted user must never get) and whether a refusal is an
acceptable answer to a permission question.

Why it exists: the development suite is frozen, and its four security cases only test whether
the model refuses (Decision 16). This separate, versioned suite tests the backend: injection
and forbidden operations in both languages, and permission cases for a restricted user.
The expected behaviour is registered in `docs/evaluation.md` before any run.

Where it sits in the pipeline: evaluation only (the eval runner loads it with
`--suite security`).
"""

from pathlib import Path
from typing import Literal

import yaml

from evals.golden import GoldenCase

SECURITY_SUITE_DIR = Path(__file__).parent / "security_suite"

# The kinds of attack and permission question. The scoring treats them in two families:
#   refusal cases:      the correct outcome is a refusal by the model or a block by the backend;
#   permission cases:   scope_own / scope_other / scope_chain / scope_control, a restricted
#                       user must get exactly the rows of their own stores.
Attack = Literal[
    "raw_schema",
    "ddl",
    "dml",
    "file_read",
    "file_write",
    "multi_statement",
    "system_function",
    "prompt_leak",
    "scope_own",
    "scope_other",
    "scope_chain",
    "scope_control",
]


class SecurityCase(GoldenCase):
    """One security or permission case.

    Attributes:
        attack: What the case tries (see `Attack`).
        forbidden_reference_sql: For permission cases: SQL on the full database whose result
            the user must NEVER receive (for example the whole-chain total for a user who may
            only see one region). If the answer equals it, the answer leaked.
        refusal_acceptable: For permission cases: True if a refusal (model or backend) is an
            acceptable answer. False for a question about the user's own region, where a
            refusal is a failure.
    """

    attack: Attack
    forbidden_reference_sql: str | None = None
    refusal_acceptable: bool = False


def load_security_suite(directory: Path = SECURITY_SUITE_DIR) -> list[SecurityCase]:
    """Load and validate all security cases.

    Args:
        directory: Folder with one YAML file per case.

    Returns:
        The cases, sorted by id.

    Raises:
        FileNotFoundError: If the folder is missing or has no case file.
        ValueError: If two files use the same id.
        pydantic.ValidationError: If a file does not match the model.
    """
    if not directory.is_dir():
        raise FileNotFoundError(f"security suite folder not found: {directory}")
    cases = [
        SecurityCase.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted(directory.glob("*.yaml"))
    ]
    if not cases:
        raise FileNotFoundError(f"no *.yaml case files in {directory}")
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids in the security suite")
    return sorted(cases, key=lambda case: case.id)
