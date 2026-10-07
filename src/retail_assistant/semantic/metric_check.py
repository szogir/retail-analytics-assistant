"""Heuristic check: does the executed SQL mention what the named metric requires?

What it does: for a metric from `metrics.yaml` it collects the column names its definition and
its mandatory filters use (for example `vat_amount`, `eur_rate`, `is_cancelled`,
`is_test_store`) and reports which of them the executed SQL does not reference at all.

Why it exists: the "What was computed" panel shows the metric the model NAMED next to the SQL
that was actually RUN. Nothing in the pipeline guarantees that the second implements the first,
so a net-sales query without the VAT column would look authoritative. This check makes the most
obvious gaps visible.

Where it sits in the pipeline: presentation only (after execution). It never blocks, changes or
grades an answer.

Design note: the check compares column NAMES, not logic. `NOT f.is_cancelled` and a SELECT of
`is_cancelled` both count as "referenced". A passing check is therefore not evidence of
correctness, and the wording in the panel says so. The alternative, proving that the SQL
equals the definition, would need a canonical form for arbitrary queries and was rejected as
out of scope.
"""

from dataclasses import dataclass
from typing import Literal

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from retail_assistant.semantic.models import Metric

CheckKind = Literal["ok", "missing", "unparsable"]


@dataclass(frozen=True)
class MetricCheck:
    """Outcome of the heuristic check for one metric.

    Attributes:
        metric: The metric name that was checked.
        kind: "ok" (nothing missing), "missing" (see `missing`) or "unparsable" (the SQL or
            the definition could not be parsed, so nothing can be said).
        missing: Column names the definition needs and the SQL never references.
    """

    metric: str
    kind: CheckKind
    missing: tuple[str, ...] = ()


def referenced_columns(sql: str) -> set[str]:
    """Return the lower-case column names a SQL text references.

    Args:
        sql: One SQL statement or expression fragment (DuckDB dialect).

    Returns:
        The set of column names, without table aliases.

    Raises:
        sqlglot.errors.SqlglotError: If the text cannot be parsed.
    """
    tree = sqlglot.parse_one(sql, read="duckdb")
    return {column.name.lower() for column in tree.find_all(exp.Column)}


def required_columns(metric: Metric) -> set[str]:
    """Return the column names a metric's expression and mandatory filters use.

    Raises:
        sqlglot.errors.SqlglotError: If the definition cannot be parsed.
    """
    # A fragment such as `SUM(f.x) / NULLIF(...)` or `NOT f.is_cancelled` parses on its own,
    # so no wrapper statement (and no string-built SELECT) is needed.
    columns = referenced_columns(metric.sql_expression)
    for predicate in metric.mandatory_filters:
        columns |= referenced_columns(predicate)
    return columns


def check_metric(metric: Metric, executed_sql: str) -> MetricCheck:
    """Compare the executed SQL with the columns one metric requires.

    Args:
        metric: A metric resolved from the semantic layer.
        executed_sql: The statement that was actually run.

    Returns:
        A `MetricCheck`; never raises for unparsable text.
    """
    try:
        needed = required_columns(metric)
        present = referenced_columns(executed_sql)
    except SqlglotError:
        return MetricCheck(metric.name, "unparsable")
    missing = tuple(sorted(needed - present))
    if missing:
        return MetricCheck(metric.name, "missing", missing)
    return MetricCheck(metric.name, "ok")
