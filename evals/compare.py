"""Result-table comparison: is the model's answer the same as the reference answer?

What it does: compares two result tables by VALUE, not by SQL text and not by column names.

Why it exists: two very different queries can give the same correct answer, and a correct
answer can come back with other column names or in another column order. Comparing the
SQL text would punish harmless differences, so the eval compares what the user would see.

Where it sits in the pipeline: evaluation only (grading step of the eval runner).

Two strictness levels are reported side by side:
- strict: same number of columns, numbers equal within a relative tolerance of 1e-6.
- lenient: extra columns are allowed (for example the model also returns the year), and
  numbers may differ by up to 1 percent (a rounding difference is not a wrong answer).
In both levels column names are ignored, column ORDER is ignored, and the order of rows
matters only for ranking questions (`order_sensitive`).
"""

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

Row = tuple[object, ...]

STRICT_REL_TOL = 1e-6
LENIENT_REL_TOL = 1e-2
# A guard against a pathological result with very many columns: trying every column
# arrangement would take too long. Such a result is simply not matched.
_MAX_COLUMN_ARRANGEMENTS = 5000


@dataclass(frozen=True)
class Comparison:
    """Outcome of comparing one answer with its reference."""

    strict: bool
    lenient: bool


def _is_number(value: object) -> bool:
    # bool is a subclass of int in Python; a yes/no column must not match the number 1.
    return isinstance(value, int | float | Decimal) and not isinstance(value, bool)


def values_equal(expected: object, actual: object, rel_tol: float) -> bool:
    """Compare two cell values.

    Numbers are compared with a relative tolerance (DuckDB returns DECIMAL, floats and
    integers for the same kind of number), text exactly (after trimming), everything else
    with ``==``.
    """
    if _is_number(expected) and _is_number(actual):
        # abs_tol covers the case "expected is exactly 0".
        return math.isclose(float(expected), float(actual), rel_tol=rel_tol, abs_tol=1e-9)  # type: ignore[arg-type]
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip() == actual.strip()
    # In Python True == 1, so a yes/no value is only equal to another yes/no value.
    if isinstance(expected, bool) != isinstance(actual, bool):
        return False
    return expected == actual


def _rows_equal(expected: Row, actual: Row, rel_tol: float) -> bool:
    return all(values_equal(e, a, rel_tol) for e, a in zip(expected, actual, strict=True))


def _tables_equal(
    expected: Sequence[Row], actual: Sequence[Row], order_sensitive: bool, rel_tol: float
) -> bool:
    """Compare two tables that already have the same columns in the same order."""
    if len(expected) != len(actual):
        return False
    if order_sensitive:
        return all(_rows_equal(e, a, rel_tol) for e, a in zip(expected, actual, strict=True))
    # Unordered: pair every expected row with a still-unused actual row that matches.
    # Design note: sorting both tables and comparing row by row would be shorter, but sorting
    # floats that differ in the last digits can put equal rows in different positions.
    unused = list(actual)
    for expected_row in expected:
        for index, candidate in enumerate(unused):
            if _rows_equal(expected_row, candidate, rel_tol):
                del unused[index]
                break
        else:
            return False
    return True


def tables_match(
    expected: Sequence[Row],
    actual: Sequence[Row],
    order_sensitive: bool,
    rel_tol: float,
    allow_extra_columns: bool,
) -> bool:
    """Decide whether the actual table contains the expected one.

    Args:
        expected: Rows of the reference result.
        actual: Rows of the model's result.
        order_sensitive: True if the row order is part of the answer.
        rel_tol: Relative tolerance for numbers.
        allow_extra_columns: If True, the actual table may have more columns than expected.

    Returns:
        True if some choice and ordering of the actual columns reproduces the expected table.
    """
    if not expected or not actual:
        return not expected and not actual
    expected_width = len(expected[0])
    actual_width = len(actual[0])
    if actual_width < expected_width:
        return False
    if actual_width > expected_width and not allow_extra_columns:
        return False
    if math.perm(actual_width, expected_width) > _MAX_COLUMN_ARRANGEMENTS:
        return False

    # Try every way to pick `expected_width` of the actual columns in any order, because
    # the model may order or select the columns differently from the reference SQL.
    for columns in itertools.permutations(range(actual_width), expected_width):
        projected = [tuple(row[index] for index in columns) for row in actual]
        if _tables_equal(expected, projected, order_sensitive, rel_tol):
            return True
    return False


def compare_tables(
    expected: Sequence[Row], actual: Sequence[Row], order_sensitive: bool
) -> Comparison:
    """Compare a model result with the reference result on both strictness levels."""
    return Comparison(
        strict=tables_match(expected, actual, order_sensitive, STRICT_REL_TOL, False),
        lenient=tables_match(expected, actual, order_sensitive, LENIENT_REL_TOL, True),
    )
