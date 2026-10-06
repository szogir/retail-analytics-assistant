"""Command-line interface: `ask` a question, or run the `eval`uation.

What it does: wires settings, model client, semantic layer and pipeline together for a person
at a terminal. `ask` prints the answer sentence, the result table and a "What was computed"
panel; `eval` starts the existing evaluation runner.

Why it exists: it is the demo surface of the project, and it must show the same behaviour the
evaluation measures, so it calls `pipeline.ask` and the eval runner instead of re-implementing
them.

Where it sits in the pipeline: outside it; it calls the pipeline and the presentation.

Run:
    uv run python -m retail_assistant.cli ask "How many stores are there?" --user anna
    uv run python -m retail_assistant.cli eval --mode semantic --profile claude_small
"""

import datetime as dt
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from retail_assistant.config import Settings
from retail_assistant.llm.factory import LLMSetup, create_llm
from retail_assistant.pipeline import Language, ask
from retail_assistant.presentation import render_answer
from retail_assistant.semantic.context import Mode
from retail_assistant.semantic.loader import load_semantic_layer
from retail_assistant.sql.access import load_users

app = typer.Typer(add_completion=False, help="Retail analytics assistant.")

# Explicit lookup tables instead of casts: an unknown value fails with a clear message and
# mypy sees that the values have the right types.
MODES: dict[str, Mode] = {"naive": "naive", "commented": "commented", "semantic": "semantic"}
LANGUAGES: dict[str, Language] = {"en": "en", "hu": "hu"}

# The only suites the CLI can start. The holdout is deliberately not in this list.
EVAL_SUITES = ("development", "security")


def build_console() -> Console:
    """The console the answer is printed to (a function so tests can replace it)."""
    return Console()


def build_llm(settings: Settings, profile: str) -> LLMSetup:
    """Create the model client (a function so tests can replace it with a fake)."""
    return create_llm(settings, profile or None)


@app.command("ask")
def ask_command(
    question: Annotated[str, typer.Argument(help="the business question")],
    user: Annotated[str, typer.Option(help="who asks: a name from config/users.yaml")] = "carla",
    lang: Annotated[str, typer.Option(help="language of the question: en or hu")] = "en",
    mode: Annotated[str, typer.Option(help="naive, commented or semantic")] = "semantic",
    profile: Annotated[str, typer.Option(help="profile from config/models.yaml")] = "",
    validator: Annotated[
        bool, typer.Option("--validator/--no-validator", help="SQL validator + user's own data")
    ] = True,
    retry: Annotated[
        bool, typer.Option("--retry/--no-retry", help="one self-correction retry after an error")
    ] = False,
    as_of: Annotated[
        str, typer.Option(help="what 'today' means, YYYY-MM-DD (default: the real today)")
    ] = "",
) -> None:
    """Ask one question and show the answer, the table and what was computed."""
    if mode not in MODES:
        raise typer.BadParameter("mode must be naive, commented or semantic")
    if lang not in LANGUAGES:
        raise typer.BadParameter("lang must be en or hu")
    if retry and not validator:
        raise typer.BadParameter("--retry needs --validator")
    try:
        today = dt.date.fromisoformat(as_of) if as_of else dt.date.today()
    except ValueError as exc:
        raise typer.BadParameter("as-of must look like 2026-10-04") from exc

    settings = Settings()
    users_path = settings.config_dir / "users.yaml"
    users = load_users(users_path)
    if user not in users:
        raise typer.BadParameter(f"unknown user '{user}'; known: {sorted(users)}")
    setup = build_llm(settings, profile)
    layer = load_semantic_layer(settings.semantic_dir)

    answer = ask(
        question,
        user,
        LANGUAGES[lang],
        MODES[mode],
        llm=setup.client,
        profile=setup.profile,
        db_path=settings.db_path,
        prompts_dir=settings.config_dir / "prompts",
        as_of=today,
        semantic_dir=settings.semantic_dir if mode == "semantic" else None,
        validate=validator,
        users_path=users_path if validator else None,
        retry=retry,
    )
    render_answer(
        build_console(),
        answer,
        lang=LANGUAGES[lang],
        user=user,
        access=users[user],
        validator_on=validator,
        layer=layer,
    )


@app.command("eval")
def eval_command(
    mode: Annotated[str, typer.Option(help="naive, commented or semantic")] = "semantic",
    profile: Annotated[str, typer.Option(help="profile from config/models.yaml")] = "",
    lang: Annotated[str, typer.Option(help="en, hu or both")] = "both",
    suite: Annotated[str, typer.Option(help="development or security")] = "development",
    validator: Annotated[
        bool, typer.Option("--validator/--no-validator", help="SQL validator + user's own data")
    ] = True,
    retry: Annotated[
        bool, typer.Option("--retry/--no-retry", help="one self-correction retry (development)")
    ] = False,
    user: Annotated[str, typer.Option(help="ask every question as this user")] = "",
    repetitions: Annotated[int, typer.Option(min=1, max=3)] = 1,
    limit: Annotated[int, typer.Option(min=0, help="only the first N cases (0 = all)")] = 0,
    compare_to: Annotated[
        Path | None, typer.Option(help="run dump (.json) of an earlier run to compare with")
    ] = None,
) -> None:
    """Run the evaluation with the existing runner and write the report."""
    # Design note: the CLI hands over to `evals.run_eval.main` instead of re-implementing the
    # loop, so `cli eval` and `python -m evals.run_eval` can never drift apart. The holdout is
    # refused here and its folder option is not offered: the sealed suite is run only as an
    # explicit owner step with the runner itself.
    if suite not in EVAL_SUITES:
        raise typer.BadParameter("the CLI runs only the development and security suites")
    # Imported here, not at the top: `ask` must work without the `evals` package next to it.
    from evals import run_eval

    run_eval.main(
        mode=mode,
        profile=profile,
        lang=lang,
        save_baseline_flag=False,
        limit=limit,
        suite=suite,
        validator=validator,
        retry=retry,
        user=user,
        repetitions=repetitions,
        compare_to=compare_to,
        holdout_dir=None,
    )


if __name__ == "__main__":
    app()
