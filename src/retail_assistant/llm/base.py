"""The provider-neutral LLM interface: protocol, result types and exceptions.

What it does: defines WHAT the rest of the application may ask of a language model
(`LLMClient.generate`) and what comes back (`LLMResult`), without naming any vendor.

Why it exists: the pipeline and the eval runner depend only on this interface. That gives
us two things: unit tests can swap in a deterministic fake (no network, no cost), and a
second provider could be added without touching the pipeline.

Where it sits in the pipeline: SQL generation step (context -> SQL generation -> ...).
"""

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

# A type variable bound to Pydantic models: `generate(..., schema=SqlAnswer)` is typed to
# return an `LLMResult[SqlAnswer]`, so mypy knows the type of `result.output` without casts.
T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Base class of every error raised by the LLM layer."""


class LLMProviderError(LLMError):
    """The provider could not be reached or rejected the request (network, auth, rate limit)."""


class LLMOutputError(LLMError):
    """The call worked, but the output is unusable (refused, truncated, not valid JSON/schema).

    Why a separate type: the eval report shows an "invalid output rate", and it must not be
    mixed up with infrastructure problems.
    """


@dataclass(frozen=True)
class Usage:
    """Token counts of one call.

    Attributes:
        input_tokens: Tokens read at the full input price (cache writes are counted here).
        output_tokens: Tokens generated.
        cached_input_tokens: Input tokens served from the prompt cache (cheaper).
    """

    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0


@dataclass(frozen=True)
class LLMResult(Generic[T]):  # noqa: UP046 (classic TypeVar style: easier to explain)
    """The validated output of one model call plus its measurements.

    Attributes:
        output: The answer, already validated against the requested Pydantic schema.
        usage: Token counts.
        latency_ms: Wall-clock time of the call in milliseconds.
        provider: Provider name, e.g. "anthropic" ("fake" for the test client).
        model: Exact model name used.
    """

    output: T
    usage: Usage
    latency_ms: float
    provider: str
    model: str


class LLMClient(Protocol):
    """What the application needs from a language model.

    Concept: a `Protocol` is structural typing ("duck typing" that mypy can check). A class
    does not have to inherit from it; it only has to have a matching `generate` method.
    """

    def generate(
        self,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResult[T]:
        """Ask the model for one structured answer.

        Args:
            system: Stable instructions (rules, schema, metrics). Kept identical between
                calls so the provider can cache it.
            user: The variable part: today's date and the question.
            schema: Pydantic model the answer must conform to.
            temperature: Sampling temperature. 0 = as deterministic as the model allows.
            max_tokens: Upper limit of generated tokens.

        Returns:
            The validated answer with usage and latency.

        Raises:
            LLMProviderError: The provider call failed.
            LLMOutputError: The output was refused, truncated or did not match the schema.
        """
        ...
