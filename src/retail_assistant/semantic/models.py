"""Pydantic models of the semantic layer files (metrics, rules, joins, examples).

What it does: describes, as typed and validated objects, what the four YAML files under
`semantic/` may contain. A file that does not fit a model is rejected with a precise message
before any prompt is built.

Why it exists: the semantic layer is business knowledge written as data. If the data were
free text, a typo in a field name would silently weaken the prompt, and the evaluation would
measure the typo instead of the idea. Validation turns such mistakes into loud errors.

Where it sits in the pipeline: context step (context -> SQL generation -> validation ->
execution -> answer). `loader.py` fills these models, `context.py` renders them into the
system prompt.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Concept: a `Source` is a pointer to what justifies an entry, so every metric, rule, join
# and example can be traced back. Three spellings are allowed:
#   contract:<section heading of docs/business_contract.md>   e.g. "contract:Measures"
#   decision:<number in docs/decisions.md>                     e.g. "decision:7"
#   schema:<table>.<column>                                    e.g. "schema:dim_store.store_id"
# Several pointers can be joined with " + " (a comma is not usable: section headings contain
# commas), e.g. "contract:Measures + schema:dim_product.name_en".
# The schema form is for facts that are not business rules but properties of the data model,
# such as a join key. Whether the target really exists is checked by
# `loader.check_sources`, because that needs the documents and the database; this pattern
# only checks the spelling.
SOURCE_SEPARATOR = " + "
_SOURCE_PATTERN = re.compile(r"^(contract:\S.*|decision:\d+|schema:[a-z_]+\.[a-z_]+)$")


class _Strict(BaseModel):
    """Base class: unknown YAML keys are errors, not silently ignored.

    Design note: Pydantic ignores extra fields by default. For a hand-written config file
    that hides typos (``synonym:`` instead of ``synonyms:``), so we forbid them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class Sourced(_Strict):
    """Mixin for every entry that must be traceable to a document."""

    source: str = Field(description="contract:<section> or decision:<number>")

    @field_validator("source")
    @classmethod
    def _source_spelling(cls, value: str) -> str:
        for part in value.split(SOURCE_SEPARATOR):
            if not _SOURCE_PATTERN.match(part):
                raise ValueError(
                    f"source must look like 'contract:<section>', 'decision:<n>' or "
                    f"'schema:<table>.<column>' (joined with ' + '): {value!r}"
                )
        return value


class Bilingual(_Strict):
    """A pair of English and Hungarian texts."""

    en: str
    hu: str


class BilingualList(_Strict):
    """Lists of English and Hungarian words that mean the same thing."""

    en: list[str] = Field(default_factory=list)
    hu: list[str] = Field(default_factory=list)


class Metric(Sourced):
    """One business measure and exactly how it is calculated.

    Attributes:
        name: Stable identifier (snake_case); other files refer to it.
        labels: Display names in both languages.
        description: What the measure means, including the traps it avoids.
        synonyms: Words users use for it.
        type: ``additive`` (a sum), ``count_distinct`` (a distinct count: not additive across
            groups) or ``ratio`` (numerator / denominator).
        expression: The SQL aggregate for additive and count_distinct metrics.
        numerator: SQL aggregate of the numerator (ratio only).
        denominator: SQL aggregate of the denominator (ratio only).
        base_table: The table the metric is calculated from (alias ``f`` in the joins).
        requires: Names of the join paths the expression and filters need.
        mandatory_filters: SQL predicates that must always be in the WHERE clause.
    """

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    labels: Bilingual
    description: str
    synonyms: BilingualList = Field(default_factory=BilingualList)
    type: Literal["additive", "count_distinct", "ratio"]
    expression: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    base_table: str
    requires: list[str] = Field(default_factory=list)
    mandatory_filters: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape_matches_type(self) -> "Metric":
        # Design note: a ratio stores numerator and denominator separately instead of one
        # free SQL string. The alternative (one `expression` for everything) would let a
        # ratio hide an "average of averages", which is the classic trap this project tests.
        if self.type == "ratio":
            if self.expression is not None or not (self.numerator and self.denominator):
                raise ValueError(f"ratio metric {self.name!r} needs numerator and denominator only")
        elif not self.expression or self.numerator or self.denominator:
            raise ValueError(f"{self.type} metric {self.name!r} needs an expression only")
        return self

    @property
    def sql_expression(self) -> str:
        """The SQL aggregate expression, built from the parts for ratios.

        Why NULLIF: a zero denominator must give NULL (undefined), never a division error
        and never a made-up zero (business contract, growth and missing-data rules).
        """
        if self.type == "ratio":
            return f"({self.numerator}) / NULLIF({self.denominator}, 0)"
        if self.expression is None:  # cannot happen after validation; kept for mypy and safety
            raise ValueError(f"metric {self.name!r} has no expression")
        return self.expression


class Rule(Sourced):
    """One business or behaviour rule the model must follow.

    Attributes:
        name: Stable identifier; examples refer to it.
        statement: The rule in plain English, as short as the contract allows.
    """

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    statement: str


class JoinPath(Sourced):
    """One allowed way to connect two tables.

    Attributes:
        name: Stable identifier; metrics refer to it in ``requires``.
        left_table / left_alias: The table already in the query and its alias.
        right_table / right_alias: The table being joined and the alias to use.
        condition: The join condition (the SQL after ON).
        description: When to use it and what to watch out for.
    """

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    left_table: str
    left_alias: str
    right_table: str
    right_alias: str
    condition: str
    description: str


class Example(Sourced):
    """A verified question -> SQL pair that shows a hard rule being applied.

    Attributes:
        id: Stable identifier.
        question: The question text (English).
        sql: A SQL statement that has been run against the database and is correct.
        demonstrates: Names of the metrics and rules the example illustrates.
    """

    id: str
    question: str
    sql: str
    demonstrates: list[str] = Field(min_length=1)


class MetricsFile(_Strict):
    """Content of ``semantic/metrics.yaml``."""

    version: int = Field(ge=1)
    metrics: list[Metric]


class RulesFile(_Strict):
    """Content of ``semantic/rules.yaml``."""

    version: int = Field(ge=1)
    rules: list[Rule]


class JoinsFile(_Strict):
    """Content of ``semantic/joins.yaml``."""

    version: int = Field(ge=1)
    base_table: str
    base_alias: str
    joins: list[JoinPath]


class ExamplesFile(_Strict):
    """Content of ``semantic/examples.yaml``."""

    version: int = Field(ge=1)
    examples: list[Example]


class SemanticLayer(_Strict):
    """The complete, cross-checked semantic layer.

    Attributes:
        metrics / rules / joins / examples: The four validated files.
        file_hashes: SHA-256 of each file's raw bytes, keyed by file name. They go into the
            evaluation report so a result can be tied to the exact semantic content.
    """

    metrics: MetricsFile
    rules: RulesFile
    joins: JoinsFile
    examples: ExamplesFile
    file_hashes: dict[str, str]

    @property
    def file_versions(self) -> dict[str, int]:
        """The ``version`` field of each file, keyed by file name."""
        return {
            "metrics.yaml": self.metrics.version,
            "rules.yaml": self.rules.version,
            "joins.yaml": self.joins.version,
            "examples.yaml": self.examples.version,
        }
