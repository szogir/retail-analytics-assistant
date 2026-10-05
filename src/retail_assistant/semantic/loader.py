"""Loader: reads and cross-checks the four YAML files of the semantic layer.

What it does: parses `metrics.yaml`, `rules.yaml`, `joins.yaml` and `examples.yaml`,
validates each against its Pydantic model, checks the references between the files and
fingerprints the raw bytes.

Why it exists: the prompt builder must receive only a layer that is internally consistent
(every join a metric needs exists, every example points at a real metric or rule). Finding a
broken reference here is cheap; finding it after a paid evaluation run is not.

Where it sits in the pipeline: context step, just before `context.py` renders the layer.
"""

import hashlib
import re
from pathlib import Path

import duckdb
import yaml
from pydantic import BaseModel, ValidationError

from retail_assistant.semantic.models import (
    SOURCE_SEPARATOR,
    ExamplesFile,
    JoinsFile,
    MetricsFile,
    RulesFile,
    SemanticLayer,
    Sourced,
)

FILE_NAMES = ("metrics.yaml", "rules.yaml", "joins.yaml", "examples.yaml")


class SemanticLayerError(Exception):
    """A semantic file is missing, unreadable, malformed or inconsistent."""


def _read_yaml[T: BaseModel](path: Path, model: type[T]) -> T:
    """Parse one YAML file into its model, naming the file in every error message."""
    # Concept: `[T: BaseModel]` is Python 3.12 generic syntax. It says "the function returns
    # the same model type that was passed in", so mypy knows `_read_yaml(p, MetricsFile)`
    # gives a `MetricsFile`, not just some BaseModel.
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SemanticLayerError(f"semantic file is missing: {path}") from exc
    try:
        # safe_load never builds arbitrary Python objects from the file.
        document = yaml.safe_load(raw)
        return model.model_validate(document)
    except (yaml.YAMLError, ValidationError) as exc:
        raise SemanticLayerError(f"{path.name} is invalid: {exc}") from exc


def _file_hash(path: Path) -> str:
    """SHA-256 of the raw bytes (not of the parsed content), so any edit changes it."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unique(names: list[str], what: str, file_name: str) -> None:
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise SemanticLayerError(f"{file_name}: duplicate {what}: {', '.join(duplicates)}")


def _cross_check(
    metrics: MetricsFile, rules: RulesFile, joins: JoinsFile, examples: ExamplesFile
) -> None:
    """Verify that names are unique and that every reference points at something real."""
    _unique([m.name for m in metrics.metrics], "metric names", "metrics.yaml")
    _unique([r.name for r in rules.rules], "rule names", "rules.yaml")
    _unique([j.name for j in joins.joins], "join names", "joins.yaml")
    _unique([e.id for e in examples.examples], "example ids", "examples.yaml")

    joins_by_name = {join.name: join for join in joins.joins}
    for metric in metrics.metrics:
        if metric.base_table != joins.base_table:
            raise SemanticLayerError(
                f"metrics.yaml: {metric.name} uses base table {metric.base_table!r}, "
                f"joins.yaml expects {joins.base_table!r}"
            )
        for join_name in metric.requires:
            join = joins_by_name.get(join_name)
            if join is None:
                raise SemanticLayerError(
                    f"metrics.yaml: {metric.name} needs unknown join {join_name!r}"
                )
            # A metric's FROM clause is the base table plus its joins. A join that starts
            # from another joined table could not be added in that simple form.
            if join.left_alias != joins.base_alias:
                raise SemanticLayerError(
                    f"metrics.yaml: {metric.name} requires {join_name!r}, which does not start "
                    f"from the base table"
                )

    known = {m.name for m in metrics.metrics} | {r.name for r in rules.rules}
    for example in examples.examples:
        unknown = [name for name in example.demonstrates if name not in known]
        if unknown:
            raise SemanticLayerError(
                f"examples.yaml: {example.id} demonstrates unknown {', '.join(unknown)}"
            )


def load_semantic_layer(directory: Path) -> SemanticLayer:
    """Load, validate and cross-check the semantic layer.

    Args:
        directory: The folder with the four YAML files (``semantic/``).

    Returns:
        The validated layer, including the SHA-256 of every file.

    Raises:
        SemanticLayerError: If a file is missing, malformed, or the files contradict each
            other. The message names the file.
    """
    metrics = _read_yaml(directory / "metrics.yaml", MetricsFile)
    rules = _read_yaml(directory / "rules.yaml", RulesFile)
    joins = _read_yaml(directory / "joins.yaml", JoinsFile)
    examples = _read_yaml(directory / "examples.yaml", ExamplesFile)
    _cross_check(metrics, rules, joins, examples)
    return SemanticLayer(
        metrics=metrics,
        rules=rules,
        joins=joins,
        examples=examples,
        file_hashes={name: _file_hash(directory / name) for name in FILE_NAMES},
    )


def _contract_sections(contract_text: str) -> set[str]:
    """Return the second-level headings of the business contract."""
    return set(re.findall(r"^## (.+?)\s*$", contract_text, flags=re.MULTILINE))


def _decision_numbers(decisions_text: str) -> set[str]:
    """Return the decision numbers; headings are '## 7. Title' or '## Decision 10: Title'."""
    return set(re.findall(r"^## (?:Decision )?(\d+)\b", decisions_text, flags=re.MULTILINE))


def _all_sourced(layer: SemanticLayer) -> list[tuple[str, Sourced]]:
    entries: list[tuple[str, Sourced]] = []
    entries += [(f"metric {m.name}", m) for m in layer.metrics.metrics]
    entries += [(f"rule {r.name}", r) for r in layer.rules.rules]
    entries += [(f"join {j.name}", j) for j in layer.joins.joins]
    entries += [(f"example {e.id}", e) for e in layer.examples.examples]
    return entries


def _schema_columns(db_path: Path) -> set[str]:
    """Return every ``table.column`` of the database (read-only; nothing is written)."""
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = connection.execute(
            "SELECT table_name, column_name FROM duckdb_columns() "
            "WHERE schema_name = 'main' AND NOT internal"
        ).fetchall()
    finally:
        connection.close()
    return {f"{table}.{column}" for table, column in rows}


def check_sources(layer: SemanticLayer, docs_dir: Path, db_path: Path) -> list[str]:
    """List every entry whose ``source`` does not point at something that exists.

    Why: "every rule is traceable" is only true if the pointer is checked. A rule whose
    source section was renamed or never existed is a rule nobody can justify.

    Args:
        layer: The loaded semantic layer.
        docs_dir: The ``docs/`` folder with business_contract.md and decisions.md.
        db_path: The DuckDB file, used to check ``schema:<table>.<column>`` sources.

    Returns:
        One problem description per bad pointer; an empty list means all sources exist.
    """
    sections = _contract_sections((docs_dir / "business_contract.md").read_text(encoding="utf-8"))
    decisions = _decision_numbers((docs_dir / "decisions.md").read_text(encoding="utf-8"))
    columns = _schema_columns(db_path)
    problems: list[str] = []
    for label, entry in _all_sourced(layer):
        for pointer in entry.source.split(SOURCE_SEPARATOR):
            kind, _, target = pointer.partition(":")
            if kind == "contract" and target not in sections:
                problems.append(f"{label}: contract section {target!r} does not exist")
            elif kind == "decision" and target not in decisions:
                problems.append(f"{label}: decision {target} does not exist")
            elif kind == "schema" and target not in columns:
                problems.append(f"{label}: column {target} does not exist")
    return problems
