"""The pipeline: one question in, one `Answer` out.

What it does: connects the steps context -> SQL generation -> execution -> answer. Day 3
version: no validator and no per-user views yet (day 5), so the only protection is that the
database is opened read-only and that only the user "carla" (full access) is accepted.

Why it exists: the CLI and the eval runner both call `ask`, so they measure and show exactly
the same behaviour.

Where it sits in the pipeline: it IS the pipeline.
"""

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from retail_assistant.llm.base import LLMClient, LLMError, LLMOutputError, Usage
from retail_assistant.llm.profiles import ModelProfile
from retail_assistant.llm.schemas import SqlAnswer
from retail_assistant.semantic.context import Mode, build_system_prompt, prompt_version
from retail_assistant.sql.executor import QueryResult, SqlExecutionError, execute_query

Language = Literal["en", "hu"]

# Output token limit of every model call. Why it is fixed here and printed in the eval report:
# an answer that hits the limit is cut off and counted as invalid output, so a different
# limit would change the accuracy number. Two runs are only comparable with the same limit.
MAX_OUTPUT_TOKENS = 4096

# What happened to the question. The eval runner grades these outcomes:
#   answered       a result table was produced
#   clarification  the model asked a question instead of guessing
#   refused        the model declined (out of scope, write request, ...)
#   sql_error      the model's SQL failed in the database
#   invalid_output the model's output was unusable (refusal by the API, bad JSON, no SQL)
#   llm_error      the provider call failed (network, auth, rate limit)
Status = Literal["answered", "clarification", "refused", "sql_error", "invalid_output", "llm_error"]


@dataclass(frozen=True)
class Answer:
    """Everything the caller needs to show or grade one answer.

    Attributes:
        status: What happened (see `Status`).
        question: The question as asked.
        message: Clarification question, refusal reason or error text; empty for a table.
        sql: The SQL that was run (or tried), empty if none.
        result: The result table when status is "answered".
        model_answer: The model's structured answer, if the call succeeded.
        usage: Token counts of the model call.
        latency_ms: Time of the model call.
        cost_usd: Price of the model call.
        prompt_version: Which prompt file was used.
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
) -> Answer:
    """Answer one question.

    Args:
        question: The business question in natural language.
        user: Who asks. Day 3: only "carla" (sees all stores) is supported.
        lang: Language of the question.
        mode: "naive" (schema only) or "semantic".
        llm: The model client (real or fake).
        profile: Model profile, used for the cost calculation.
        db_path: The DuckDB file.
        prompts_dir: Folder with the versioned prompt files.
        as_of: What "today" means for relative dates such as "last month".

    Returns:
        An `Answer`. Model and SQL failures do not raise; they become a status, because the
        eval must count them instead of crashing.

    Raises:
        ValueError: If the user is not supported yet.
        NotImplementedError: If the mode is not implemented yet.
    """
    # Why refuse instead of ignoring: silently giving another user the full data would be a
    # permission bug. Per-user filtered views arrive on day 5.
    if user != "carla":
        raise ValueError(f"user '{user}' is not supported before day 5 (per-user access)")

    version = prompt_version(mode)
    system = build_system_prompt(mode, db_path, prompts_dir)

    try:
        generated = llm.generate(
            system,
            build_user_prompt(question, lang, as_of),
            SqlAnswer,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
    except LLMOutputError as exc:
        return Answer("invalid_output", question, message=str(exc), prompt_version=version)
    except LLMError as exc:
        return Answer("llm_error", question, message=str(exc), prompt_version=version)

    model_answer = generated.output

    def finish(
        status: Status, message: str = "", sql: str = "", result: QueryResult | None = None
    ) -> Answer:
        """Build the Answer with the measurements of this model call filled in."""
        return Answer(
            status=status,
            question=question,
            message=message,
            sql=sql,
            result=result,
            model_answer=model_answer,
            usage=generated.usage,
            latency_ms=generated.latency_ms,
            cost_usd=profile.cost_usd(generated.usage),
            prompt_version=version,
        )

    if model_answer.needs_clarification:
        return finish(
            "clarification", message=model_answer.clarification_question or model_answer.approach
        )
    if model_answer.intent == "out_of_scope":
        return finish("refused", message=model_answer.approach)
    if not model_answer.sql.strip():
        return finish("invalid_output", message="the answer contains no SQL")

    try:
        result = execute_query(db_path, model_answer.sql)
    except SqlExecutionError as exc:
        return finish("sql_error", message=str(exc), sql=model_answer.sql)
    return finish("answered", sql=model_answer.sql, result=result)
