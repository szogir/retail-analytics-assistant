"""Context builder: assembles the system prompt the model receives.

What it does: reads the versioned prompt file and fills in the database schema.

Why it exists: the project's central experiment compares two kinds of context. "naive"
gives the model only the table and column names; "commented" adds the stored column comments;
"semantic" adds metric definitions, rules, join paths and verified examples. All three are
built here, so the only difference between two eval runs is the context.

Where it sits in the pipeline: first step (context -> SQL generation -> validation ->
execution -> answer).
"""

from pathlib import Path
from typing import Literal

import duckdb

from retail_assistant.semantic.loader import load_semantic_layer
from retail_assistant.semantic.models import SemanticLayer

Mode = Literal["naive", "commented", "semantic"]
# Which parts of the semantic layer go into the prompt (ablation study, Decision 23).
# "full" is the frozen v3 prompt; the others leave out examples, rules, or both. Metrics and
# join paths are always kept: without them the semantic mode would just be "commented".
Ablation = Literal["full", "no_examples", "no_rules", "metrics_joins"]
ABLATIONS: tuple[Ablation, ...] = ("full", "no_examples", "no_rules", "metrics_joins")

# The placeholder in the prompt file. Plain str.replace is used instead of str.format
# because the prompt text may contain curly braces (JSON, SQL) that format would misread.
_SCHEMA_PLACEHOLDER = "{schema}"
_SEMANTIC_PLACEHOLDER = "{semantic}"

# Version of the prompt file per mode; it is printed in every eval report.
PROMPT_FILES: dict[Mode, str] = {
    "naive": "sql_naive_v1.md",
    "commented": "sql_commented_v1.md",
    "semantic": "sql_semantic_v1.md",
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


def render_semantic_section(layer: SemanticLayer, ablation: Ablation = "full") -> str:
    """Render the semantic layer as the text block that goes into the system prompt.

    Why plain text and not JSON: the model reads it like documentation. Short labelled lines
    cost fewer tokens than nested JSON and keep each definition next to its SQL.

    Args:
        layer: The validated semantic layer.
        ablation: Which sections to include. "full" renders all four; "no_examples" leaves
            out Verified examples, "no_rules" leaves out Rules, "metrics_joins" leaves out both.
            An omitted section disappears together with its heading.

    Returns:
        Markdown text with the sections Rules, Metrics, Join paths and Verified examples
        (minus the omitted ones). The text is deterministic (file order), so the prompt stays
        cacheable.

    Raises:
        ValueError: For an unknown ablation name.
    """
    if ablation not in ABLATIONS:
        raise ValueError(f"unknown ablation '{ablation}'")
    include_rules = ablation in ("full", "no_examples")
    include_examples = ablation in ("full", "no_rules")

    # Design note: the "full" path must produce exactly the frozen v3 text (Decision 15), so
    # the sections are only skipped, never rewritten. The alternative, one prompt file per
    # variant, would also change the surrounding template, i.e. two things at once.
    lines: list[str] = []
    if include_rules:
        lines += ["### Rules", ""]
        for rule in layer.rules.rules:
            lines.append(f"- `{rule.name}`: {rule.statement}")
        lines.append("")

    lines += ["### Metrics", ""]
    lines.append(
        f"Aliases: {layer.joins.base_alias} = {layer.joins.base_table}; "
        "the other aliases are listed under Join paths."
    )
    for metric in layer.metrics.metrics:
        synonyms = ", ".join(metric.synonyms.en + metric.synonyms.hu)
        lines += [
            "",
            f"**{metric.name}** ({metric.type}) - {metric.labels.en} / {metric.labels.hu}",
            f"- Meaning: {metric.description}",
            f"- Also called: {synonyms}",
            f"- SQL: `{metric.sql_expression}`",
            f"- Joins needed: {', '.join(metric.requires) or 'none'}",
            f"- Always filter: {' AND '.join(metric.mandatory_filters) or 'nothing'}",
        ]

    lines += ["", "### Join paths", ""]
    for join in layer.joins.joins:
        lines.append(
            f"- `{join.name}`: JOIN {join.right_table} {join.right_alias} ON {join.condition} "
            f"(from {join.left_table} {join.left_alias}). {join.description}"
        )

    if include_examples:
        lines += ["", "### Verified examples", ""]
        for example in layer.examples.examples:
            lines += [
                f"Question: {example.question}",
                f"Rules and metrics shown: {', '.join(example.demonstrates)}",
                "```sql",
                example.sql.strip(),
                "```",
                "",
            ]
    return "\n".join(lines).rstrip() + "\n"


def prompt_version(mode: Mode) -> str:
    """Return the prompt file name (the version label) used for a mode.

    Raises:
        NotImplementedError: For a mode without a prompt file.
    """
    if mode not in PROMPT_FILES:
        raise NotImplementedError(f"mode '{mode}' is not implemented yet")
    return PROMPT_FILES[mode].removesuffix(".md")


def build_system_prompt(
    mode: Mode,
    db_path: Path,
    prompts_dir: Path,
    semantic_dir: Path | None = None,
    ablation: Ablation = "full",
) -> str:
    """Build the stable system prompt for a mode.

    Args:
        mode: "naive" (schema only), "commented" (schema plus column comments) or
            "semantic" (commented schema plus the semantic layer).
        db_path: The DuckDB file whose schema is described.
        prompts_dir: Folder with the versioned prompt files (`config/prompts`).
        semantic_dir: Folder with the semantic YAML files; required for "semantic".
        ablation: Which parts of the semantic layer to include (see
            `render_semantic_section`). Only "full" is allowed outside the semantic mode.

    Returns:
        The system prompt text. It contains no question and no date, so it is identical
        between calls and the provider can cache it.

    Raises:
        NotImplementedError: If the mode has no prompt file.
        ValueError: If the mode is "semantic" and no semantic folder was given, or an
            ablation other than "full" is asked for in another mode.
        FileNotFoundError: If the prompt file is missing.
        SemanticLayerError: If the semantic files are invalid.
    """
    prompt_version(mode)  # raises for an unimplemented mode
    if ablation != "full" and mode != "semantic":
        # Why refuse: naive and commented have no semantic layer to leave parts out of; a
        # silently ignored flag would label a run as an ablation that was not one.
        raise ValueError("an ablation is only defined for the semantic mode")
    template = (prompts_dir / PROMPT_FILES[mode]).read_text(encoding="utf-8")
    schema = describe_schema(db_path, include_comments=mode in ("commented", "semantic"))
    prompt = template.replace(_SCHEMA_PLACEHOLDER, schema)
    if mode != "semantic":
        return prompt
    if semantic_dir is None:
        raise ValueError("the semantic mode needs the folder with the semantic files")
    # The semantic text is inserted last, so a "{schema}" inside it can never be replaced.
    layer = load_semantic_layer(semantic_dir)
    return prompt.replace(_SEMANTIC_PLACEHOLDER, render_semantic_section(layer, ablation))
