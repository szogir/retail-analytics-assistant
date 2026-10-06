"""The pipeline: one question in, one `Answer` out.

What it does: connects the steps context -> SQL generation -> validation -> user connection
-> execution -> answer. With `validate=True` (day 5) the model's SQL must pass the validator
and runs on a connection that only holds the asking user's stores. With `validate=False` the
original day-3 path runs unchanged (database opened read-only, only "carla" accepted); it
exists so that earlier measurements stay reproducible.

Why it exists: the CLI and the eval runner both call `ask`, so they measure and show exactly
the same behaviour.

Where it sits in the pipeline: it IS the pipeline.
"""

import datetime as dt
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from retail_assistant.llm.base import LLMClient, LLMError, LLMOutputError, LLMResult, Usage
from retail_assistant.llm.profiles import ModelProfile
from retail_assistant.llm.schemas import SqlAnswer
from retail_assistant.semantic.context import Mode, build_system_prompt, prompt_version
from retail_assistant.sql.access import AccessError, UserAccess, load_users, open_user_connection
from retail_assistant.sql.executor import (
    QueryResult,
    SqlExecutionError,
    execute_query,
    run_on_connection,
)
from retail_assistant.sql.validator import RULE_PARSE_ERROR, validate_sql

Language = Literal["en", "hu"]

# Output token limit of every model call. Why it is fixed here and printed in the eval report:
# an answer that hits the limit is cut off and counted as invalid output, so a different
# limit would change the accuracy number. Two runs are only comparable with the same limit.
MAX_OUTPUT_TOKENS = 4096

# Row limit and timeout of every statement run on the validated path (same values as the
# defaults of `execute_query`).
ROW_LIMIT = 1000
TIMEOUT_SECONDS = 30.0

# Statuses after which the single retry may happen (see `ask`).
RETRYABLE: tuple[str, ...] = ("sql_error", "blocked")

# What happened to the question. The eval runner grades these outcomes:
#   answered       a result table was produced
#   clarification  the model asked a question instead of guessing
#   refused        the model declined (out of scope, write request, ...)
#   sql_error      the model's SQL failed in the database (or could not even be parsed)
#   blocked        the validator refused the SQL because it breaks a safety rule; it was not run
#   invalid_output the model's output was unusable (refusal by the API, bad JSON, no SQL)
#   llm_error      the provider call failed (network, auth, rate limit)
Status = Literal[
    "answered", "clarification", "refused", "sql_error", "blocked", "invalid_output", "llm_error"
]


@dataclass(frozen=True)
class Answer:
    """Everything the caller needs to show or grade one answer.

    Attributes:
        status: What happened (see `Status`).
        question: The question as asked.
        message: Clarification question, refusal reason or error text; empty for a table.
            For "blocked" it names the violated rules and tokens.
        sql: The SQL that was run (or tried), empty if none.
        result: The result table when status is "answered".
        model_answer: The model's structured answer, if the call succeeded.
        usage: Token counts of the model call.
        latency_ms: Time of the model call.
        cost_usd: Price of the model call.
        prompt_version: Which prompt file was used.
        blocked_rules: Rule names that made the validator refuse the SQL (status "blocked").
        retried: True if a second model call was made after a "sql_error" or "blocked" result.
        retry_succeeded: True if that retry ended in status "answered".
        first_status: Status of the first attempt, also when a retry changed the final status.
    """

    status: Status
    question: str
    message: str = ""
    sql: str = ""
    result: QueryResult | None = None
    model_answer: SqlAnswer | None = None
    usage: Usage | None = None
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    prompt_version: str = ""
    blocked_rules: tuple[str, ...] = field(default_factory=tuple)
    retried: bool = False
    retry_succeeded: bool = False
    first_status: str = ""


def build_user_prompt(question: str, lang: Language, as_of: dt.date) -> str:
    """Build the variable part of the prompt: today's date, language and the question.

    Why the date is here and not in the system prompt: the system prompt must stay
    byte-identical between calls to be cacheable, and "today" is the one thing that changes.
    """
    return f"Today's date: {as_of.isoformat()}\nQuestion language: {lang}\nQuestion: {question}"


def ask(
    question: str,
    user: str,
    lang: Language,
    mode: Mode,
    *,
    llm: LLMClient,
    profile: ModelProfile,
    db_path: Path,
    prompts_dir: Path,
    as_of: dt.date,
    semantic_dir: Path | None = None,
    validate: bool = False,
    users_path: Path | None = None,
    retry: bool = False,
) -> Answer:
    """Answer one question.

    Args:
        question: The business question in natural language.
        user: Who asks. With `validate=True` the name must be in `users.yaml`; without it
            only "carla" (sees all stores) is supported.
        lang: Language of the question.
        mode: "naive" (schema only), "commented" or "semantic".
        llm: The model client (real or fake).
        profile: Model profile, used for the cost calculation.
        db_path: The DuckDB file.
        prompts_dir: Folder with the versioned prompt files.
        as_of: What "today" means for relative dates such as "last month".
        semantic_dir: Folder with the semantic layer files; needed for the "semantic" mode.
        validate: True = backend protection on: validator, then execution on the user's own
            filtered connection. False = the original path, kept for reproducible measurements.
        users_path: `users.yaml`; required when `validate` is True.
        retry: True = after a "sql_error" or "blocked" result, ask the model once more with
            the error text. Needs `validate=True`. Default False, so earlier runs stay
            reproducible.

    Why `validate` defaults to False: the eval runner and the existing measurements were made
    without the backend layers, and a silent default change would make runs incomparable. The
    CLI and every run that claims backend protection pass True explicitly, and the run info
    records it.

    Returns:
        An `Answer`. Model and SQL failures do not raise; they become a status, because the
        eval must count them instead of crashing.

    Raises:
        ValueError: If the user is unknown, `validate` is set without `users_path`, or
            `retry` is set without `validate`.
    """
    # Why refuse instead of ignoring: silently giving another user the full data would be a
    # permission bug. Only the validated path knows per-user access.
    if retry and not validate:
        # Why: a retried statement must pass the validator and the user's connection again;
        # the legacy path has neither, so a retry there would be an unprotected second chance.
        raise ValueError("retry=True needs validate=True")
    access = None
    if validate:
        if users_path is None:
            raise ValueError("validate=True needs users_path")
        access = load_users(users_path).get(user)
        if access is None:
            raise ValueError(f"unknown user '{user}'")
    elif user != "carla":
        raise ValueError(f"user '{user}' is not supported without validate=True")

    version = prompt_version(mode)
    system = build_system_prompt(mode, db_path, prompts_dir, semantic_dir)

    user_prompt = build_user_prompt(question, lang, as_of)
    try:
        generated = llm.generate(
            system,
            user_prompt,
            SqlAnswer,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
    except LLMOutputError as exc:
        return Answer(
            "invalid_output",
            question,
            message=str(exc),
            prompt_version=version,
            first_status="invalid_output",
        )
    except LLMError as exc:
        return Answer(
            "llm_error",
            question,
            message=str(exc),
            prompt_version=version,
            first_status="llm_error",
        )

    outcome = _judge(generated.output, access, db_path)
    first = generated
    first_status = outcome.status
    retried = False
    if retry and outcome.status in RETRYABLE:
        # Design note: exactly one retry, and only for failures the model can plausibly fix
        # from the error text (a SQL error or a validator rule). Clarifications, refusals and
        # invalid output are decisions or format problems, not mistakes to "correct". The
        # alternative, a loop of several retries, would hide how often the first answer was
        # wrong and make cost and latency unbounded.
        retried = True
        try:
            second = llm.generate(
                system,
                build_retry_prompt(user_prompt, outcome),
                SqlAnswer,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
        except LLMError:
            second = None  # keep the first outcome; the failed retry still counts as a retry
        if second is not None:
            # The retried SQL goes through the same judge: validator, user connection, executor.
            outcome = _judge(second.output, access, db_path)
            generated = _combine(first, second)

    return Answer(
        status=outcome.status,
        question=question,
        message=outcome.message,
        sql=outcome.sql,
        result=outcome.result,
        model_answer=generated.output,
        usage=generated.usage,
        latency_ms=generated.latency_ms,
        cost_usd=profile.cost_usd(generated.usage),
        prompt_version=version,
        blocked_rules=outcome.blocked_rules,
        retried=retried,
        retry_succeeded=retried and outcome.status == "answered",
        first_status=first_status,
    )


def _combine(first: LLMResult[SqlAnswer], second: LLMResult[SqlAnswer]) -> LLMResult[SqlAnswer]:
    """Merge two calls: the second output, but tokens and latency of both (cost is honest)."""
    usage = Usage(
        input_tokens=first.usage.input_tokens + second.usage.input_tokens,
        output_tokens=first.usage.output_tokens + second.usage.output_tokens,
        cached_input_tokens=first.usage.cached_input_tokens + second.usage.cached_input_tokens,
        cache_creation_input_tokens=first.usage.cache_creation_input_tokens
        + second.usage.cache_creation_input_tokens,
    )
    return replace(second, usage=usage, latency_ms=first.latency_ms + second.latency_ms)


@dataclass(frozen=True)
class _Outcome:
    """What one model answer led to, before the measurements are attached."""

    status: Status
    message: str = ""
    sql: str = ""
    result: QueryResult | None = None
    blocked_rules: tuple[str, ...] = ()


def build_retry_prompt(user_prompt: str, failed: _Outcome) -> str:
    """Extend the user prompt with the failed SQL and its error, for the single retry.

    Why only the error text: the model sees what it wrote and why it failed, never any data
    rows, so the retry cannot be used to read results the user may not see.
    """
    return (
        f"{user_prompt}\n\nYour previous SQL was rejected.\n"
        f"SQL: {failed.sql}\nProblem: {failed.message}\n"
        "Return a corrected answer, or ask for clarification if the question cannot be "
        "answered safely."
    )


def _judge(model_answer: SqlAnswer, access: UserAccess | None, db_path: Path) -> _Outcome:
    """Turn one model answer into an outcome: classify, validate, execute.

    Why a function: the first answer and the retry must take exactly the same path through
    the validator and the user's connection, so there is one copy of that logic.
    """
    if model_answer.needs_clarification:
        return _Outcome(
            "clarification", model_answer.clarification_question or model_answer.approach
        )
    if model_answer.intent == "out_of_scope":
        return _Outcome("refused", model_answer.approach)
    sql = model_answer.sql
    if not sql.strip():
        return _Outcome("invalid_output", "the answer contains no SQL")

    if access is None:
        try:
            return _Outcome("answered", sql=sql, result=execute_query(db_path, sql))
        except SqlExecutionError as exc:
            return _Outcome("sql_error", str(exc), sql)

    verdict = validate_sql(sql)
    if not verdict.ok:
        # Design note: unparsable SQL is a plain SQL error, not a security block. The database
        # would reject it anyway; calling it "blocked" would fill the security statistics with
        # typos (the 4 such statements in the recorded runs were all of this kind).
        if verdict.rules == [RULE_PARSE_ERROR]:
            return _Outcome("sql_error", verdict.summary(), sql)
        return _Outcome(
            "blocked", verdict.summary(), sql, blocked_rules=tuple(dict.fromkeys(verdict.rules))
        )

    try:
        connection = open_user_connection(db_path, access)
    except AccessError as exc:
        return _Outcome("sql_error", str(exc), sql)
    try:
        result = run_on_connection(connection, sql, ROW_LIMIT, TIMEOUT_SECONDS)
    except SqlExecutionError as exc:
        return _Outcome("sql_error", str(exc), sql)
    finally:
        connection.close()
    return _Outcome("answered", sql=sql, result=result)
