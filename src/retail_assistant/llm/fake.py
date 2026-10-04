"""Deterministic fake LLM client for unit tests and offline demos.

What it does: implements `LLMClient` without any network: it returns prepared answers (or
raises prepared errors) and records every call it received.

Why it exists: unit tests must be fast, free and repeatable, and they must never call the
real API. Because the fake has the same interface as the Claude adapter, the pipeline and
the eval runner can be tested end to end.

Where it sits in the pipeline: stands in for the SQL generation step.
"""

from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from retail_assistant.llm.base import LLMError, LLMResult, T, Usage

# A responder looks at (system, user) and decides the answer: handy when the answer depends
# on the question, e.g. in an evaluation run over many cases.
Responder = Callable[[str, str], BaseModel | LLMError]


# A module-level constant, because a function call in a default argument is evaluated only once.
DEFAULT_USAGE = Usage(input_tokens=1000, output_tokens=200)


@dataclass(frozen=True)
class FakeCall:
    """One recorded call, so tests can assert what the pipeline sent."""

    system: str
    user: str
    schema: type[BaseModel]
    temperature: float
    max_tokens: int


class FakeLLMClient:
    """`LLMClient` that returns scripted answers.

    Args:
        responses: Answers (or errors to raise) returned in order, one per call.
        responder: Alternative to `responses`: a function that picks the answer per call.
        usage: Token counts reported for every call.
        latency_ms: Latency reported for every call.

    Raises:
        ValueError: If neither or both of `responses` and `responder` are given.
    """

    def __init__(
        self,
        responses: Sequence[BaseModel | LLMError] | None = None,
        responder: Responder | None = None,
        usage: Usage = DEFAULT_USAGE,
        latency_ms: float = 5.0,
    ) -> None:
        if (responses is None) == (responder is None):
            raise ValueError("give exactly one of `responses` or `responder`")
        self._queue: deque[BaseModel | LLMError] = deque(responses or [])
        self._responder = responder
        self._usage = usage
        self._latency_ms = latency_ms
        self.calls: list[FakeCall] = []

    def generate(
        self,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResult[T]:
        """Return the next scripted answer (see `LLMClient.generate`).

        Raises:
            LLMError: If the next scripted item is an error (it is raised, as a real client
                would).
            AssertionError: If the script ran out, or the answer has the wrong type.
        """
        self.calls.append(FakeCall(system, user, schema, temperature, max_tokens))
        if self._responder is not None:
            item = self._responder(system, user)
        elif self._queue:
            item = self._queue.popleft()
        else:
            raise AssertionError("FakeLLMClient has no more scripted responses")

        if isinstance(item, LLMError):
            raise item
        if not isinstance(item, schema):
            raise AssertionError(f"scripted answer is {type(item).__name__}, not {schema.__name__}")
        return LLMResult(
            output=item,
            usage=self._usage,
            latency_ms=self._latency_ms,
            provider="fake",
            model="fake-model",
        )
