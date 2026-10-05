"""SQL validator: decides whether a model-written statement may be run at all.

What it does: parses the SQL into a syntax tree (sqlglot, DuckDB dialect) and checks it
against a small set of rules: exactly one statement, a read-only query, only allow-listed
tables, no schema qualification (so no `raw` schema), only allow-listed table functions and
no file / system / meta functions.

Why it exists: the model's output is untrusted input. The prompt asks the model to refuse
dangerous requests, but a prompt is a request, not a control (Decision 16: the naive and
commented modes failed 3 and 6 of 24 security questions). This module is the first of two
independent backend layers; the second is the per-user connection in `access.py`.

Where it sits in the pipeline: validation step (context -> SQL generation -> VALIDATION ->
execution -> answer).

Design note: the row limit is NOT enforced here. Wrapping the statement in
`SELECT * FROM (...) LIMIT n` would change a query that has its own `ORDER BY` (DuckDB does
not guarantee that a subquery's order survives), and `WITH`/`UNION` statements are awkward to
wrap. The executor already fetches at most `row_limit + 1` rows and reports `truncated`, which
caps the result without touching the query text.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

# The only tables and views the model may read. The per-user views in `access.py` carry the
# same names, so one list serves both.
ALLOWED_TABLES = frozenset(
    {"dim_date", "dim_holiday", "dim_product", "dim_store", "fact_sales", "fx_rate"}
)

# Table functions that only generate values and cannot reach files or other tables.
# Design note: an allow-list, not a deny-list, because DuckDB has dozens of table functions
# (read_csv, parquet_scan, query_table, sniff_csv, glob, duckdb_tables, ...) and a new
# extension can add more. Anything not listed here is refused.
ALLOWED_TABLE_FUNCTIONS = frozenset({"range", "generate_series", "unnest"})

# Scalar functions that reach outside the query. Design note: here a deny-list is the only
# practical choice, because the model legitimately uses hundreds of ordinary functions (sum,
# strftime, round, ...); an allow-list would block valid analytics.
FORBIDDEN_FUNCTIONS = frozenset(
    {
        "query",  # runs a SQL string, so it can read any table
        "query_table",  # reads a table named by a string
        "getvariable",
        "current_setting",
        "getenv",
        "glob",
        "which_secret",
        "load_extension",
        "install_extension",
    }
)
# File readers and system catalogs come in families: read_csv, read_text, read_blob,
# parquet_scan, sniff_csv, duckdb_settings, pragma_database_list, ...
FORBIDDEN_FUNCTION_PREFIXES = ("read_", "sniff_", "duckdb_", "pragma_", "parquet_", "iceberg_")
FORBIDDEN_FUNCTION_SUFFIXES = ("_scan",)

# Rule names, stable strings so that tests and reports can count them.
RULE_PARSE_ERROR = "parse_error"
RULE_SINGLE_STATEMENT = "single_statement"
RULE_SELECT_ONLY = "select_only"
RULE_RAW_SCHEMA = "raw_schema"
RULE_QUALIFIED_TABLE = "qualified_table"
RULE_TABLE_NOT_ALLOWED = "table_not_allowed"
RULE_TABLE_FUNCTION = "table_function_not_allowed"
RULE_FORBIDDEN_FUNCTION = "forbidden_function"
RULE_NON_QUERY_NODE = "non_query_statement"

# A query is a SELECT, a set operation (UNION/EXCEPT/INTERSECT) of SELECTs, or a WITH on top
# of them (sqlglot attaches the WITH to the select, so the root is still a Select).
_QUERY_ROOTS = (exp.Select, exp.SetOperation)
# Nodes that are never part of a read-only query, wherever they appear in the tree.
_FORBIDDEN_NODES = (exp.Command, exp.Attach, exp.Copy, exp.Pragma, exp.Install, exp.Set)


@dataclass(frozen=True)
class Issue:
    """One rule violation.

    Attributes:
        rule: Stable rule name (e.g. "raw_schema"), for machines and statistics.
        token: The offending piece of SQL (e.g. "raw.fact_sales"), for people.
        message: A sentence that names the rule and the token.
    """

    rule: str
    token: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of `validate_sql`.

    Attributes:
        issues: Every violation found (empty when the SQL is allowed).
    """

    issues: tuple[Issue, ...] = ()

    @property
    def ok(self) -> bool:
        """True if the SQL may be run."""
        return not self.issues

    @property
    def rules(self) -> list[str]:
        """Rule names of all issues, in order."""
        return [issue.rule for issue in self.issues]

    def summary(self) -> str:
        """One line for logs and for the answer message, e.g. `[raw_schema] 'raw.x': ...`."""
        return "; ".join(f"[{i.rule}] {i.message}" for i in self.issues)


def _issue(rule: str, token: str, explanation: str) -> Issue:
    return Issue(rule, token, f"'{token}' {explanation}")


def _function_name(node: exp.Func) -> str:
    """Lower-case name of a function call, typed (exp.Sum) or unknown (exp.Anonymous)."""
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def _is_forbidden_function(name: str) -> bool:
    return (
        name in FORBIDDEN_FUNCTIONS
        or name.startswith(FORBIDDEN_FUNCTION_PREFIXES)
        or name.endswith(FORBIDDEN_FUNCTION_SUFFIXES)
    )


def _check_tables(root: exp.Expression) -> list[Issue]:
    """Check every table reference and table function in the statement."""
    issues: list[Issue] = []
    # A name defined by this statement's own WITH clause is a legal reference.
    cte_names = {str(cte.alias).lower() for cte in root.find_all(exp.CTE)}
    for table in root.find_all(exp.Table):
        source = table.this
        if isinstance(source, exp.Func):
            name = _function_name(source)
            if name not in ALLOWED_TABLE_FUNCTIONS:
                issues.append(_issue(RULE_TABLE_FUNCTION, name, "is not an allowed table function"))
            continue
        text = table.sql(dialect="duckdb")
        schema = str(table.args["db"].name).lower() if table.args.get("db") else ""
        catalog = str(table.args["catalog"].name).lower() if table.args.get("catalog") else ""
        if "raw" in (schema, catalog):
            issues.append(_issue(RULE_RAW_SCHEMA, text, "reaches the hidden raw schema"))
        elif schema or catalog:
            issues.append(
                _issue(RULE_QUALIFIED_TABLE, text, "is schema-qualified; use the plain table name")
            )
        elif str(table.name).lower() not in ALLOWED_TABLES | cte_names:
            issues.append(_issue(RULE_TABLE_NOT_ALLOWED, text, "is not an allowed table"))
    return issues


def _check_functions(root: exp.Expression) -> list[Issue]:
    """Check scalar function calls; table functions were already handled by `_check_tables`."""
    issues: list[Issue] = []
    for node in root.find_all(exp.Func):
        if isinstance(node.parent, exp.Table):
            continue
        name = _function_name(node)
        if _is_forbidden_function(name):
            issues.append(
                _issue(RULE_FORBIDDEN_FUNCTION, name, "is a file, system or meta function")
            )
    return issues


def validate_sql(sql: str) -> ValidationResult:
    """Check one SQL string against the safety rules.

    Args:
        sql: The statement written by the model.

    Returns:
        A `ValidationResult`; `ok` is True only if no rule was violated. Never raises: a
        string that cannot be parsed is a `parse_error` issue.

    Why: all rules are evaluated on the parsed tree, so comments, string literals, quoting
    and unusual whitespace cannot hide a table or a function from the check.
    """
    # Design note: sqlglot parses into a tree for the DuckDB dialect. The alternative,
    # `sqlparse`, only tokenizes and cannot reliably tell a table from a string literal.
    try:
        parsed = sqlglot.parse(sql, read="duckdb")
    except SqlglotError as exc:
        return ValidationResult((Issue(RULE_PARSE_ERROR, "", f"cannot be parsed: {exc}"),))

    # A trailing semicolon yields an empty entry (None); it is not a second statement.
    statements = [statement for statement in parsed if statement is not None]
    if not statements:
        return ValidationResult((Issue(RULE_PARSE_ERROR, "", "the SQL is empty"),))
    if len(statements) > 1:
        return ValidationResult(
            (_issue(RULE_SINGLE_STATEMENT, f"{len(statements)} statements", "found; send one"),)
        )

    root = statements[0]
    # `isinstance` of the whole tuple: Select covers WITH, SetOperation covers UNION & co.
    if not isinstance(root, _QUERY_ROOTS):
        return ValidationResult(
            (_issue(RULE_SELECT_ONLY, type(root).__name__, "is not a read-only SELECT"),)
        )

    issues: list[Issue] = []
    for node in root.find_all(*_FORBIDDEN_NODES):
        issues.append(_issue(RULE_NON_QUERY_NODE, type(node).__name__, "is not allowed"))
    issues.extend(_check_tables(root))
    issues.extend(_check_functions(root))
    return ValidationResult(tuple(issues))
