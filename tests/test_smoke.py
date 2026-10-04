"""Smoke test: proves the package is importable and the test setup works.

It is intentionally trivial. Its job is to keep CI green from the very first
commit, so every later change is checked by the same pipeline.
"""

import retail_assistant


def test_package_has_version() -> None:
    assert retail_assistant.__version__ == "0.1.0"
