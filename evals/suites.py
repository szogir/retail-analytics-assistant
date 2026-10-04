"""Resolve suite locations without exposing sealed cases to development by default.

Only an explicit holdout request consults HOLDOUT_DIR. No repository-local fallback
exists, so CI and ordinary development can operate without possessing sealed data.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def suite_directory(suite: str, holdout_dir: Path | None = None) -> Path:
    """Resolve a development suite or an explicitly configured external holdout.

    Args:
        suite: Either development or holdout.
        holdout_dir: Explicit external path, taking precedence over HOLDOUT_DIR.

    Returns:
        An existing absolute suite directory.

    Raises:
        ValueError: For unknown suites, missing configuration or an in-repository holdout.
        FileNotFoundError: If the configured directory does not exist.
    """
    if suite == "development":
        return PROJECT_ROOT / "evals" / "golden_set"
    if suite != "holdout":
        raise ValueError("suite must be development or holdout")
    configured = str(holdout_dir) if holdout_dir is not None else os.environ.get("HOLDOUT_DIR", "")
    if not configured.strip():
        raise ValueError("Holdout location missing: set HOLDOUT_DIR or pass --holdout-dir")
    directory = Path(configured).expanduser().resolve()
    if directory.is_relative_to(PROJECT_ROOT.resolve()):
        raise ValueError("The holdout directory must be outside the repository")
    if not directory.is_dir():
        raise FileNotFoundError(f"Configured holdout directory does not exist: {directory}")
    return directory
