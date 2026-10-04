"""Context builder: assembles the system prompt the model receives.

What it does: reads the versioned prompt file and fills in the database schema.

Why it exists: the project's central experiment compares two kinds of context. "naive"
gives the model only the table and column names; "semantic" (day 4) will add metric
definitions, join paths and verified examples. Both are built here, so the only difference
between the two eval runs is the context.

Where it sits in the pipeline: first step (context -> SQL generation -> validation ->
execution -> answer).
"""

from pathlib import Path
from typing import Literal

import duckdb

Mode = Literal["naive", "commented", "semantic"]

# The placeholder in the prompt file. Plain str.replace is used instead of str.format
# because the prompt text may contain curly braces (JSON, SQL) that format would misread.
_SCHEMA_PLACEHOLDER = "{schema}"

# Version of the prompt file per mode; it is printed in every eval report.
PROMPT_FILES: dict[Mode, str] = {
    "naive": "sql_naive_v1.md",
    "commented": "sql_commented_v1.md",
}


def describe_schema(db_path: Path, include_comments: bool = False) -> str:
    """Describe all tables of the database as one line per table.

    Args:
        db_path: The DuckDB file.
        include_comments: Include stored column metadata, but no metric definitions.

    Returns:
        Text like ``dim_store(store_id INTEGER, store_name VARCHAR, ...)``, one table per
        line, tables in alphabetical order.
    """
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = connection.execute(
            "SELECT table_name, column_name, data_type, comment FROM duckdb_columns() "
            "WHERE schema_name = 'main' AND NOT internal "
            "AND database_name = current_database() ORDER BY table_name, column_index"
        ).fetchall()
    finally:
        connection.close()

    columns_by_table: dict[str, list[str]] = {}
    for table, column, data_type, comment in rows:
        metadata = f" [{comment}]" if include_comments and comment else ""
        columns_by_table.setdefault(table, []).append(f"{column} {data_type}{metadata}")
    return "\n".join(f"{table}({', '.join(cols)})" for table, cols in columns_by_table.items())


def prompt_version(mode: Mode) -> str:
    """Return the prompt file name (the version label) used for a mode.

    Raises:
        NotImplementedError: For the "semantic" mode, which arrives on day 4.
    """
    if mode not in PROMPT_FILES:
        raise NotImplementedError(f"mode '{mode}' is not implemented yet")
    return PROMPT_FILES[mode].removesuffix(".md")


def build_system_prompt(mode: Mode, db_path: Path, prompts_dir: Path) -> str:
    """Build the stable system prompt for a mode.

    Args:
        mode: "naive" (schema only) or "semantic".
        db_path: The DuckDB file whose schema is described.
        prompts_dir: Folder with the versioned prompt files (`config/prompts`).

    Returns:
        The system prompt text. It contains no question and no date, so it is identical
        between calls and the provider can cache it.

    Raises:
        NotImplementedError: If the mode is not implemented yet.
        FileNotFoundError: If the prompt file is missing.
    """
    prompt_version(mode)  # raises for an unimplemented mode
    template = (prompts_dir / PROMPT_FILES[mode]).read_text(encoding="utf-8")
    return template.replace(
        _SCHEMA_PLACEHOLDER, describe_schema(db_path, include_comments=mode == "commented")
    )
