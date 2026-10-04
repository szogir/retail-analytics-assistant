"""The structured answer the model must produce (`SqlAnswer`).

What it does: defines the exact shape of the model output as a Pydantic model.

Why it exists: free text would have to be parsed with fragile rules. A schema lets the API
constrain the output and lets us validate it once, at the border of our system.

Where it sits in the pipeline: output of the SQL generation step, input of validation /
execution.
"""

from typing import Literal

from pydantic import BaseModel, Field


# Design note: the class docstring below is NOT only documentation. Pydantic puts it into the
# JSON schema that is sent to the model as the `description` of the object. Keep it short and
# free of talk about "reasoning" or "thinking": Claude Sonnet 5.5 has a safety classifier
# ("reasoning_extraction") that blocked such requests in a live experiment (stop reason
# "refusal"). The same applies to the field names: this field was first called `reasoning`
# and was blocked, `approach` passes. Haiku 4.5 did not mind either, but both profiles must
# use the same schema to stay comparable.
#
# Why `approach` comes BEFORE `sql`: the model writes its output token by token in field
# order, so describing the plan first gives it a chance to work out the business rules
# before it commits to a query.
class SqlAnswer(BaseModel):
    """The model's structured answer to one question.

    Attributes:
        language: Language of the question.
        intent: What kind of request it is (a data question, a definition, or not answerable).
        approach: How the question is interpreted and which steps lead to the SQL, in the
            language of the question.
        sql: One SELECT statement; empty when no SQL is needed.
        metrics_used: Names of the measures that were calculated.
        assumptions: Assumptions made while interpreting the question.
        needs_clarification: True if the question is too vague to answer.
        clarification_question: The question to ask the user instead of guessing.
    """

    language: Literal["en", "hu"]
    intent: Literal["metric_query", "definition", "out_of_scope"]
    approach: str
    sql: str = ""
    metrics_used: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str = ""
