"""Tests of the SQL validator: attacks one by one, and the false-positive gate.

The gate runs every SQL the project already trusts (reference SQL, verified examples, metric
expressions) and every SQL a model produced in a recorded development run through the
validator. Trusted SQL must pass; for recorded model SQL only statements that really break a
rule may be blocked, and the blocked ones are listed in `EXPECTED_BLOCKS` with the reason.
"""

import json
from collections import Counter
from pathlib import Path

import duckdb
import pytest
import yaml

from evals.golden import load_golden_set
from retail_assistant.sql.validator import (
    ALLOWED_TABLES,
    validate_sql,
)

ROOT = Path(__file__).resolve().parents[1]

ALLOWED_SQL = [
    "SELECT 1",
    "SELECT 1;",  # a trailing semicolon is not a second statement
    "SELECT * FROM fact_sales",
    'SELECT * FROM "fact_sales"',
    "FROM fact_sales SELECT count(*)",  # DuckDB FROM-first syntax, still a SELECT
    "WITH a AS (SELECT 1 AS x) SELECT * FROM a",
    "WITH a AS (SELECT 1 AS x), b AS (SELECT x FROM a) SELECT * FROM b",
    "SELECT 1 UNION ALL SELECT 2",
    "SELECT * FROM range(3)",
    "SELECT * FROM generate_series(1, 3) AS t(x)",
    "SELECT d.date FROM dim_date d WHERE d.date IN (SELECT sales_date FROM fact_sales)",
    "SELECT sum(x) OVER (PARTITION BY y ORDER BY z) FROM (SELECT 1 x, 2 y, 3 z) q",
    "SELECT * FROM fact_sales -- raw.fact_sales in a comment",
    "SELECT 'raw.fact_sales read_csv(x)' AS text_only",  # forbidden words inside a literal
]

# (sql, rule that must be reported)
ATTACKS = [
    # --- more than one statement / not a SELECT
    ("SELECT 1; SELECT 2", "single_statement"),
    ("SELECT 1; DROP TABLE fact_sales", "single_statement"),
    ("DROP TABLE fact_sales", "select_only"),
    ("DELETE FROM fact_sales", "select_only"),
    ("UPDATE fact_sales SET quantity = 0", "select_only"),
    ("INSERT INTO fact_sales SELECT * FROM fact_sales", "select_only"),
    ("CREATE TABLE x AS SELECT 1", "select_only"),
    ("ALTER TABLE fact_sales ADD COLUMN x INT", "select_only"),
    ("ATTACH 'other.duckdb' AS o", "select_only"),
    ("COPY (SELECT 1) TO 'out.csv'", "select_only"),
    ("COPY fact_sales FROM 'in.csv'", "select_only"),
    ("PRAGMA database_list", "select_only"),
    ("INSTALL httpfs", "select_only"),
    ("LOAD httpfs", "select_only"),
    ("SET enable_external_access = true", "select_only"),
    ("CALL pragma_database_list()", "select_only"),
    ("DESCRIBE fact_sales", "select_only"),
    ("SUMMARIZE fact_sales", "select_only"),
    # --- raw schema and qualified names, in every position and spelling
    ("SELECT * FROM raw.fact_sales", "raw_schema"),
    ("SELECT * FROM raw.main.fact_sales", "raw_schema"),
    ('SELECT * FROM "raw".main."fact_sales"', "raw_schema"),
    ('SELECT * FROM "RAW".fact_sales', "raw_schema"),
    ("SELECT * FROM dim_date WHERE d IN (SELECT d FROM raw.dim_date)", "raw_schema"),
    ("WITH a AS (SELECT * FROM raw.fact_sales) SELECT * FROM a", "raw_schema"),
    ("SELECT * FROM main.fact_sales", "qualified_table"),
    ("SELECT * FROM information_schema.tables", "qualified_table"),
    ("SELECT * FROM temp.main.fact_sales", "qualified_table"),
    # --- tables that are not on the list
    ("SELECT * FROM secrets", "table_not_allowed"),
    ("SELECT * FROM 'data.csv'", "table_not_allowed"),
    ("SELECT * FROM 'data.parquet'", "table_not_allowed"),
    ("SELECT * FROM fact_sales f JOIN other o ON o.id = f.store_id", "table_not_allowed"),
    # --- table functions (allow-list)
    ("SELECT * FROM read_csv('x.csv')", "table_function_not_allowed"),
    ("SELECT * FROM read_csv_auto('x.csv')", "table_function_not_allowed"),
    ("SELECT * FROM read_parquet('x.parquet')", "table_function_not_allowed"),
    ("SELECT * FROM read_json('x.json')", "table_function_not_allowed"),
    ("SELECT * FROM read_text('x.txt')", "table_function_not_allowed"),
    ("SELECT * FROM read_blob('x.bin')", "table_function_not_allowed"),
    ("SELECT * FROM sniff_csv('x.csv')", "table_function_not_allowed"),
    ("SELECT * FROM parquet_scan('x.parquet')", "table_function_not_allowed"),
    ("SELECT * FROM csv_scan('x.csv')", "table_function_not_allowed"),
    ("SELECT * FROM glob('*')", "table_function_not_allowed"),
    ("SELECT * FROM query_table('fact_sales')", "table_function_not_allowed"),
    ("SELECT * FROM query_table('raw.fact_sales')", "table_function_not_allowed"),
    ("SELECT * FROM duckdb_tables()", "table_function_not_allowed"),
    ("SELECT * FROM duckdb_settings()", "table_function_not_allowed"),
    ("SELECT * FROM pragma_database_list()", "table_function_not_allowed"),
    ("SELECT * FROM read_csv('x.csv'), fact_sales", "table_function_not_allowed"),
    # --- scalar functions (deny-list)
    ("SELECT query('SELECT * FROM raw.fact_sales')", "forbidden_function"),
    ("SELECT query_table('raw.fact_sales')", "forbidden_function"),
    ("SELECT read_text('/etc/passwd')", "forbidden_function"),
    ("SELECT read_blob('x.bin')", "forbidden_function"),
    ("SELECT current_setting('home_directory')", "forbidden_function"),
    ("SELECT getvariable('secret')", "forbidden_function"),
    ("SELECT getenv('API_KEY')", "forbidden_function"),
    (
        "SELECT (SELECT count(*) FROM fact_sales WHERE query('SELECT 1') IS NOT NULL)",
        "forbidden_function",
    ),
    ("SELECT sum(quantity) FROM fact_sales WHERE read_text('x') = 'y'", "forbidden_function"),
    # --- hiding tricks must not work
    ("sElEcT * FrOm RaW.fact_sales", "raw_schema"),
    ("SELECT * FROM /* x */ raw /* y */ . /* z */ fact_sales", "raw_schema"),
    ("SELECT 1 -- harmless\n; DROP TABLE fact_sales", "single_statement"),
    ("SELECT 1 /* ; */ ; SELECT 2", "single_statement"),
]

# Unparsable or empty input is refused, not crashed on.
BROKEN = ["", "   ", "SELECT (((", "SELEC * FROM", ";"]

# sqlglot cannot parse these DuckDB commands at all; failing closed (parse_error) is correct.
UNPARSABLE_COMMANDS = ["EXPORT DATABASE 'dir'", "IMPORT DATABASE 'dir'"]


@pytest.mark.parametrize("sql", ALLOWED_SQL)
def test_allowed_sql_passes(sql: str) -> None:
    result = validate_sql(sql)
    assert result.ok, result.summary()


@pytest.mark.parametrize(("sql", "rule"), ATTACKS)
def test_attack_is_blocked_by_the_named_rule(sql: str, rule: str) -> None:
    result = validate_sql(sql)
    assert not result.ok
    assert rule in result.rules, result.summary()


@pytest.mark.parametrize("sql", BROKEN)
def test_broken_input_is_refused_without_raising(sql: str) -> None:
    result = validate_sql(sql)
    assert not result.ok
    assert result.rules == ["parse_error"]


@pytest.mark.parametrize("sql", UNPARSABLE_COMMANDS)
def test_unparsable_commands_fail_closed(sql: str) -> None:
    assert not validate_sql(sql).ok


def test_message_names_rule_and_token() -> None:
    issue = validate_sql("SELECT * FROM raw.fact_sales").issues[0]
    assert issue.rule == "raw_schema"
    assert "raw.fact_sales" in issue.token
    assert "[raw_schema]" in validate_sql("SELECT * FROM raw.fact_sales").summary()
    assert "raw.fact_sales" in issue.message


def test_cte_may_not_hide_a_forbidden_table() -> None:
    # The CTE name is allowed, but the table it reads is checked as well.
    result = validate_sql("WITH a AS (SELECT * FROM secrets) SELECT * FROM a")
    assert result.rules == ["table_not_allowed"]


def test_all_issues_are_reported_not_only_the_first() -> None:
    result = validate_sql("SELECT read_text('x') FROM raw.fact_sales")
    assert set(result.rules) == {"forbidden_function", "raw_schema"}


def test_allowed_tables_match_the_database_schema(full_db_path: Path) -> None:
    connection = duckdb.connect(str(full_db_path), read_only=True)
    names = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    connection.close()
    assert names == set(ALLOWED_TABLES)


# ---------------------------------------------------------------------------------------
# False-positive gate
# ---------------------------------------------------------------------------------------

_METRIC_FROM = (
    "FROM fact_sales f JOIN dim_store s ON s.store_id = f.store_id "
    "JOIN dim_product p ON p.product_id = f.product_id "
    "JOIN dim_date d ON d.date = f.sales_date "
    "JOIN fx_rate fx ON fx.rate_date = f.sales_date AND fx.currency = f.currency"
)


def trusted_sql() -> dict[str, str]:
    """Every SQL the project wrote and verified itself, keyed by where it comes from."""
    found: dict[str, str] = {}
    for case in load_golden_set():
        if case.reference_sql:
            found[f"reference:{case.id}"] = case.reference_sql
    examples = yaml.safe_load((ROOT / "semantic" / "examples.yaml").read_text(encoding="utf-8"))
    for example in examples["examples"]:
        found[f"example:{example['id']}"] = example["sql"]
    metrics = yaml.safe_load((ROOT / "semantic" / "metrics.yaml").read_text(encoding="utf-8"))
    for metric in metrics["metrics"]:
        # An expression is only a fragment; put it into a complete query over the usual joins.
        # Ratio metrics have a numerator and a denominator instead of one expression.
        parts = [metric["expression"]] if "expression" in metric else []
        parts += [metric[key] for key in ("numerator", "denominator") if key in metric]
        for index, part in enumerate(parts):
            found[f"metric:{metric['name']}:{index}"] = f"SELECT {part} {_METRIC_FROM}"
    return found


def recorded_model_sql() -> list[tuple[str, str, str]]:
    """(file, mode, sql) of every model answer in the recorded runs under evals/results."""
    found: list[tuple[str, str, str]] = []
    for path in sorted((ROOT / "evals" / "results").rglob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        # Run dumps have {"info", "results": [..]}; paired-analysis files have other shapes.
        if not isinstance(document, dict) or not isinstance(document.get("results"), list):
            continue
        mode = str(document.get("info", {}).get("mode", "?"))
        for row in document["results"]:
            if isinstance(row, dict) and row.get("sql"):
                found.append((path.name, mode, str(row["sql"])))
    return found


def test_trusted_sql_all_passes() -> None:
    blocked = {
        name: validate_sql(sql).summary()
        for name, sql in trusted_sql().items()
        if not validate_sql(sql).ok
    }
    assert blocked == {}


def test_recorded_model_sql_is_blocked_only_when_it_would_fail_anyway(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """A recorded model SQL may only be blocked if DuckDB itself rejects it.

    Why: the gate must show that the validator does not take away a working answer. Every
    blocked statement is run against the real database; if one of them returns rows, the
    validator has a false positive.
    """
    false_positives: dict[str, str] = {}
    for file_name, mode, sql in recorded_model_sql():
        result = validate_sql(sql)
        if result.ok:
            continue
        try:
            db.execute(sql).fetchmany(1)
        except duckdb.Error:
            continue  # blocked, and the database would have failed it too
        false_positives[f"{file_name} [{mode}] {sql[:80]}"] = result.summary()
    assert false_positives == {}


def test_gate_report(capsys: pytest.CaptureFixture[str]) -> None:
    """Print how many recorded SQLs were checked and which rules blocked how many."""
    trusted = trusted_sql()
    recorded = recorded_model_sql()
    counts: Counter[str] = Counter()
    for _, _, sql in recorded:
        result = validate_sql(sql)
        counts.update(set(result.rules))
    blocked = sum(1 for _, _, sql in recorded if not validate_sql(sql).ok)
    with capsys.disabled():
        print(f"\nGATE trusted={len(trusted)} recorded={len(recorded)} blocked={blocked}")
        print(f"GATE rules={dict(counts)}")
    assert len(trusted) > 50
    assert len(recorded) > 500
