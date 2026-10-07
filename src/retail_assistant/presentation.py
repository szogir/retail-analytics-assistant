"""Presentation: turns an `Answer` into text and terminal output (no model, no database).

What it does: builds the answer sentence with a fixed template, formats the result table and
the "What was computed" panel, and looks up metric definitions in the semantic layer.

Why it exists: what the user reads must be traceable. Every number on the screen comes from
the result table (formatted by the functions below) and every metric definition comes from
`semantic/metrics.yaml`. The model's own words are shown only where they are labelled as the
model's (assumptions, refusal reason, clarification question).

Where it sits in the pipeline: after the answer step; the CLI calls it, the eval does not.
"""

from collections.abc import Sequence
from decimal import Decimal

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from retail_assistant.pipeline import Answer, Language
from retail_assistant.semantic.metric_check import check_metric
from retail_assistant.semantic.models import Metric, SemanticLayer
from retail_assistant.sql.access import UserAccess

# How many result rows the terminal table shows. The full result (up to the executor's row
# limit) was computed; a screen full of rows helps nobody.
MAX_TABLE_ROWS = 25

# Fixed texts per language. Design note: a plain dictionary instead of gettext. Two languages
# and a few dozen strings do not justify translation tooling, and every string stays visible
# in one place.
TEXTS: dict[Language, dict[str, str]] = {
    "en": {
        "answer": "Answer",
        "no_rows": "The query returned no rows.",
        "one_value": "{name}: {value}",
        "many_rows": "{count} rows, columns: {columns}. The table below is the answer.",
        "truncated": "The result was cut at the row limit; more rows exist.",
        "clarification": "I need one more detail before I can answer: {text}",
        "refused": "I cannot answer this question. The model's reason: {text}",
        "definition": "Definition of {label}: {description}",
        "blocked": "The request was blocked by the safety checks and was not run. Rules: {rules}.",
        "sql_error": "The generated SQL could not be run: {text}",
        "invalid_output": "The model's answer was unusable: {text}",
        "llm_error": "The model could not be reached: {text}",
        "computed": "What was computed",
        "user": "User",
        "validator": "Validator",
        "validator_off": "off",
        "validator_passed": "passed; ran on the user's own filtered connection",
        "validator_blocked": "BLOCKED by rule(s): {rules}",
        "validator_none": "no SQL reached the validator",
        "sql": "SQL actually executed",
        "metrics": "Metric named by the model (catalogue definition, not the executed code)",
        "no_metrics": "(none named)",
        "check_none": "Heuristic check: no catalogue metric named, no check",
        "check_missing": "⚠ heuristic check: SQL does not reference {columns} ({metric})",
        "check_ok": (
            "Heuristic check found no missing element ({metric}); it compares column "
            "names only and does not prove the SQL is correct"
        ),
        "check_unparsable": "Heuristic check not possible ({metric}): could not parse the SQL",
        "unidentified": "not an identifiable metric",
        "assumptions": "Assumptions (stated by the model)",
        "none": "(none)",
        "latency": "Model latency",
        "cost": "Cost",
        "retry": "Retry",
        "retry_used": "one retry made; ended as {status}",
        "scope_all": "all stores",
        "scope_regions": "regions {regions}",
        "filters": "always filtered by",
        "more_rows": "... {count} more rows not shown",
    },
    "hu": {
        "answer": "Válasz",
        "no_rows": "A lekérdezés nem adott vissza sort.",
        "one_value": "{name}: {value}",
        "many_rows": "{count} sor, oszlopok: {columns}. A válasz az alábbi táblázat.",
        "truncated": "Az eredmény a sorlimitnél csonkolva lett; több sor is van.",
        "clarification": "Még egy részletre van szükségem a válaszhoz: {text}",
        "refused": "Erre a kérdésre nem tudok válaszolni. A modell indoka: {text}",
        "definition": "{label} definíciója: {description}",
        "blocked": "A kérést a biztonsági ellenőrzés blokkolta, nem futott le. Szabályok: {rules}.",
        "sql_error": "A generált SQL nem futtatható: {text}",
        "invalid_output": "A modell válasza használhatatlan volt: {text}",
        "llm_error": "A modell nem érhető el: {text}",
        "computed": "Mit számoltunk",
        "user": "Felhasználó",
        "validator": "Validátor",
        "validator_off": "ki",
        "validator_passed": "átment; a felhasználó saját szűrt kapcsolatán futott",
        "validator_blocked": "BLOKKOLVA, szabály: {rules}",
        "validator_none": "nem érkezett SQL a validátorhoz",
        "sql": "Ténylegesen futtatott SQL",
        "metrics": (
            "A modell által megnevezett metrika (katalógus-definíció, nem a futtatott kód)"
        ),
        "no_metrics": "(nincs megnevezve)",
        "check_none": (
            "Heurisztikus ellenőrzés: nincs megnevezett katalógus-metrika, nincs ellenőrzés"
        ),
        "check_missing": (
            "⚠ heurisztikus ellenőrzés: az SQL nem hivatkozik erre: {columns} ({metric})"
        ),
        "check_ok": (
            "A heurisztikus ellenőrzés nem talált hiányzó elemet ({metric}); csak oszlopneveket "
            "hasonlít, nem bizonyítja az SQL helyességét"
        ),
        "check_unparsable": (
            "Heurisztikus ellenőrzés nem lehetséges ({metric}): az SQL nem értelmezhető"
        ),
        "unidentified": "nem azonosítható metrika",
        "assumptions": "Feltevések (a modell állítja)",
        "none": "(nincs)",
        "latency": "Modell késleltetése",
        "cost": "Költség",
        "retry": "Újrapróbálás",
        "retry_used": "egy újrapróbálás történt; vége: {status}",
        "scope_all": "minden bolt",
        "scope_regions": "régiók {regions}",
        "filters": "mindig szűrve",
        "more_rows": "... még {count} sor, nincs megjelenítve",
    },
}


def format_value(value: object, lang: Language) -> str:
    """Format one cell of the result table for display.

    Why here and not in the model: a number the user reads must be the database's number. This
    function only changes its appearance (thousand separators, decimals), never its value.

    Args:
        value: A value from the result table.
        lang: "en" (1,234.50) or "hu" (1 234,50).

    Returns:
        The text to show.
    """
    if value is None:
        return "-"
    # bool is a subclass of int in Python, so it must be checked first.
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        text = f"{value:,}"
    elif isinstance(value, (float, Decimal)):
        text = f"{value:,.2f}"
    else:
        return str(value)
    if lang == "hu":
        return text.replace(",", " ").replace(".", ",")
    return text


def resolve_metrics(names: Sequence[str], layer: SemanticLayer) -> tuple[list[Metric], list[str]]:
    """Split the model's `metrics_used` into known metrics and unidentified names.

    Why exact matching: the model may write "net sales" or "Net Sales EUR". Guessing which
    metric it meant would present a definition the model never used. Only a name that equals a
    `metrics.yaml` name exactly is resolved; the rest is shown as text, labelled unidentified.

    Args:
        names: The `metrics_used` list of the model.
        layer: The semantic layer.

    Returns:
        (resolved metrics in the model's order without duplicates, unidentified names).
    """
    by_name = {metric.name: metric for metric in layer.metrics.metrics}
    resolved: list[Metric] = []
    unidentified: list[str] = []
    for name in names:
        metric = by_name.get(name)
        if metric is None:
            if name not in unidentified:
                unidentified.append(name)
        elif metric not in resolved:
            resolved.append(metric)
    return resolved, unidentified


def answer_text(answer: Answer, lang: Language, metrics: Sequence[Metric] = ()) -> str:
    """Build the answer sentence from a fixed template.

    Design note: deterministic template instead of a second model call that "summarises" the
    table. A model-written summary can state a number the table does not contain, would need
    its own check, and adds cost and latency. The template cannot invent a figure: every digit
    comes from `format_value` applied to the table (or is the row count).

    The period is deliberately not stated: the model's assumptions are free text, so a date in
    them is not a verified fact. If the result has a date column, it is in the table.

    Args:
        answer: The pipeline result.
        lang: Language of the text.
        metrics: Metrics resolved from `metrics_used` (used only to name a single value).

    Returns:
        The text to show above the table.
    """
    texts = TEXTS[lang]
    model_text = answer.message
    if answer.status == "clarification":
        return texts["clarification"].format(text=model_text)
    if answer.status == "refused":
        return texts["refused"].format(text=model_text)
    if answer.status == "definition":
        # The text is the catalogue's own, never the model's. The pipeline only sets this status
        # for one exactly matching metric, so `metrics` has that metric.
        if len(metrics) != 1:
            return texts["invalid_output"].format(text=model_text)
        metric = metrics[0]
        label = metric.labels.hu if lang == "hu" else metric.labels.en
        return texts["definition"].format(label=label, description=metric.description.strip())
    if answer.status == "blocked":
        return texts["blocked"].format(rules=", ".join(answer.blocked_rules))
    if answer.status in ("sql_error", "invalid_output", "llm_error"):
        return texts[answer.status].format(text=model_text)

    result = answer.result
    if result is None or not result.rows:
        return texts["no_rows"]
    lines: list[str] = []
    if len(result.rows) == 1 and len(result.columns) == 1:
        # One number. It is named after the metric only when exactly one metric was resolved;
        # with zero or several the column name is the only honest label.
        name = None
        if len(metrics) == 1:
            name = metrics[0].labels.hu if lang == "hu" else metrics[0].labels.en
        lines.append(
            texts["one_value"].format(
                name=name or result.columns[0], value=format_value(result.rows[0][0], lang)
            )
        )
    else:
        lines.append(
            texts["many_rows"].format(
                count=format_value(len(result.rows), lang), columns=", ".join(result.columns)
            )
        )
    if result.truncated:
        lines.append(texts["truncated"])
    return "\n".join(lines)


def result_table(answer: Answer, lang: Language) -> Table | None:
    """Build the rich table of the result, or None if there is no result."""
    result = answer.result
    if result is None or not result.rows:
        return None
    table = Table(show_lines=False)
    for column in result.columns:
        table.add_column(Text(column), justify="left")
    for row in result.rows[:MAX_TABLE_ROWS]:
        table.add_row(*(Text(format_value(value, lang)) for value in row))
    hidden = len(result.rows) - MAX_TABLE_ROWS
    if hidden > 0:
        table.caption = TEXTS[lang]["more_rows"].format(count=format_value(hidden, lang))
    return table


def _metric_definition(metric: Metric, lang: Language) -> str:
    label = metric.labels.hu if lang == "hu" else metric.labels.en
    lines = [f"{metric.name} - {label}: {metric.description.strip()}"]
    lines.append(f"  = {metric.sql_expression}")
    if metric.mandatory_filters:
        filters = " AND ".join(metric.mandatory_filters)
        lines.append(f"  {TEXTS[lang]['filters']}: {filters}")
    return "\n".join(lines)


def _check_lines(sql: str, resolved: Sequence[Metric], lang: Language) -> list[str]:
    """Lines of the heuristic check for the executed SQL (see `metric_check`).

    Why no tick on success: the check compares column names only. A success message that looked
    like approval would claim more than the check knows.
    """
    texts = TEXTS[lang]
    if not resolved:
        return [texts["check_none"]]
    lines: list[str] = []
    for metric in resolved:
        outcome = check_metric(metric, sql)
        if outcome.kind == "missing":
            lines.append(
                texts["check_missing"].format(
                    columns=", ".join(outcome.missing), metric=outcome.metric
                )
            )
        elif outcome.kind == "ok":
            lines.append(texts["check_ok"].format(metric=outcome.metric))
        else:
            lines.append(texts["check_unparsable"].format(metric=outcome.metric))
    return lines


def _validator_line(answer: Answer, validator_on: bool, lang: Language) -> str:
    texts = TEXTS[lang]
    if not validator_on:
        return texts["validator_off"]
    if answer.status == "blocked":
        return texts["validator_blocked"].format(rules=", ".join(answer.blocked_rules))
    if answer.status == "answered":
        return texts["validator_passed"]
    return texts["validator_none"] if not answer.sql else answer.status


def _scope_text(access: UserAccess | None, lang: Language) -> str:
    texts = TEXTS[lang]
    if access is None or access.all_stores:
        return texts["scope_all"]
    return texts["scope_regions"].format(regions=", ".join(str(r) for r in access.region_ids))


def computed_panel(
    answer: Answer,
    *,
    lang: Language,
    user: str,
    access: UserAccess | None,
    validator_on: bool,
    layer: SemanticLayer,
) -> Panel:
    """Build the "What was computed" panel.

    Args:
        answer: The pipeline result.
        lang: Language of the labels.
        user: Who asked.
        access: What that user may see (shown as the scope), None if unknown.
        validator_on: Whether the backend protection was on.
        layer: The semantic layer, for the metric definitions.

    Returns:
        A rich panel.
    """
    texts = TEXTS[lang]
    metric_names = answer.model_answer.metrics_used if answer.model_answer else []
    resolved, unidentified = resolve_metrics(metric_names, layer)
    # Text(...) instead of plain strings: model words and SQL names may contain square
    # brackets, which rich would otherwise read as markup.
    parts: list[RenderableType] = [
        Text(f"{texts['user']}: {user} ({_scope_text(access, lang)})"),
        Text(f"{texts['validator']}: {_validator_line(answer, validator_on, lang)}"),
    ]
    if answer.sql:
        parts.append(Text(f"{texts['sql']}:"))
        parts.append(Syntax(answer.sql, "sql", word_wrap=True))
    parts.append(Text(f"{texts['metrics']}:"))
    if not resolved and not unidentified:
        parts.append(Text(f"  {texts['no_metrics']}"))
    for metric in resolved:
        parts.append(Text(_metric_definition(metric, lang)))
    for name in unidentified:
        # Shown as plain text, with no definition: the name is the model's wording.
        parts.append(Text(f"{name} - {texts['unidentified']}"))
    if answer.sql:
        parts.extend(Text(line) for line in _check_lines(answer.sql, resolved, lang))
    assumptions = answer.model_answer.assumptions if answer.model_answer else []
    parts.append(Text(f"{texts['assumptions']}:"))
    for assumption in assumptions or [texts["none"]]:
        parts.append(Text(f"  - {assumption}"))
    parts.append(Text(f"{texts['latency']}: {answer.latency_ms:.0f} ms"))
    parts.append(Text(f"{texts['cost']}: ${answer.cost_usd:.5f}"))
    if answer.retried:
        parts.append(Text(f"{texts['retry']}: {texts['retry_used'].format(status=answer.status)}"))
    return Panel(Group(*parts), title=texts["computed"], title_align="left")


def render_answer(
    console: Console,
    answer: Answer,
    *,
    lang: Language,
    user: str,
    access: UserAccess | None,
    validator_on: bool,
    layer: SemanticLayer,
) -> None:
    """Print the answer text, the result table and the "What was computed" panel."""
    metric_names = answer.model_answer.metrics_used if answer.model_answer else []
    resolved, _ = resolve_metrics(metric_names, layer)
    console.print(f"[bold]{TEXTS[lang]['answer']}[/bold]")
    # Text(...): the sentence contains model words; square brackets in them must not be read
    # as rich markup.
    console.print(Text(answer_text(answer, lang, resolved)))
    table = result_table(answer, lang)
    if table is not None:
        console.print(table)
    console.print(
        computed_panel(
            answer,
            lang=lang,
            user=user,
            access=access,
            validator_on=validator_on,
            layer=layer,
        )
    )
