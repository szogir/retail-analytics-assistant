"""Claude adapter: implements `LLMClient` with the official Anthropic SDK.

What it does: sends one request to the Messages API and returns the answer already parsed
into the requested Pydantic model (structured output), with token usage and latency.

Why it exists: it is the only module that knows about the Anthropic SDK. Everything else
talks to the `LLMClient` protocol.

Where it sits in the pipeline: SQL generation step.
"""

import time
from typing import Any

import anthropic
from pydantic import ValidationError

from retail_assistant.llm.base import (
    LLMOutputError,
    LLMProviderError,
    LLMResult,
    T,
    Usage,
)
from retail_assistant.llm.profiles import ModelProfile


class AnthropicClient:
    """`LLMClient` implementation for Claude models.

    Args:
        profile: Model name, prices and request options.
        api_key: API key. If None, the SDK looks for credentials by itself.
        sdk_client: A ready SDK client; given only by tests, so no network is needed.
    """

    def __init__(
        self,
        profile: ModelProfile,
        api_key: str | None = None,
        sdk_client: anthropic.Anthropic | None = None,
    ) -> None:
        self._profile = profile
        self._client = sdk_client or anthropic.Anthropic(api_key=api_key)

    def generate(
        self,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResult[T]:
        """Ask Claude for one structured answer (see `LLMClient.generate`).

        Raises:
            LLMProviderError: The API call failed (network, auth, rate limit, server error).
            LLMOutputError: Claude refused, hit the token limit, or the JSON did not fit.
        """
        request: dict[str, Any] = {
            "model": self._profile.model,
            "max_tokens": max_tokens,
            # Why a block with cache_control: the system prompt is identical for every
            # question, so the provider can serve it from its cache at a lower price.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "output_format": schema,
        }
        # Design note: the SDK's typed `parse()` has no temperature argument and the newest
        # models reject it. The profile says whether the model accepts one; if so it goes in
        # as an extra body field. The alternative, always sending it, would break those models.
        if self._profile.supports_temperature:
            request["extra_body"] = {"temperature": temperature}
        request.update(self._profile.request_options)

        started = time.perf_counter()
        try:
            response = self._client.messages.parse(**request)
        except anthropic.APIError as exc:
            raise LLMProviderError(f"Anthropic API call failed: {exc}") from exc
        except ValidationError as exc:
            # The SDK validates the JSON against our Pydantic model while parsing, so it raises
            # instead of returning the response. The tokens were billed all the same.
            raise LLMOutputError(
                f"model output does not match {schema.__name__}: {exc}",
                usage=_usage_from_traceback(exc),
                latency_ms=(time.perf_counter() - started) * 1000,
            ) from exc
        latency_ms = (time.perf_counter() - started) * 1000
        usage = _usage_of(response.usage)

        if response.stop_reason == "refusal":
            raise LLMOutputError("the model refused to answer", usage, latency_ms)
        if response.stop_reason == "max_tokens":
            raise LLMOutputError(f"output cut off at max_tokens={max_tokens}", usage, latency_ms)
        output = response.parsed_output
        if not isinstance(output, schema):
            raise LLMOutputError(f"no parsed {schema.__name__} in the response", usage, latency_ms)

        return LLMResult(
            output=output,
            usage=usage,
            latency_ms=latency_ms,
            provider="anthropic",
            model=self._profile.model,
        )


def _usage_of(sdk_usage: Any) -> Usage:
    """Convert the SDK's usage object into our `Usage`."""
    return Usage(
        input_tokens=sdk_usage.input_tokens,
        output_tokens=sdk_usage.output_tokens,
        cached_input_tokens=sdk_usage.cache_read_input_tokens or 0,
        # Design note: cache writes have their own price (1.25x input for the 5-minute cache).
        # Earlier code folded them into input_tokens, which under-priced them.
        cache_creation_input_tokens=sdk_usage.cache_creation_input_tokens or 0,
    )


def _usage_from_traceback(error: BaseException) -> Usage | None:
    """Recover the usage of a response that the SDK failed to parse.

    Why this exists: `messages.parse` downloads the response and parses it in one call. When the
    JSON does not fit our schema it raises, and the response object is only still reachable as
    the `response` argument of the SDK's parser frame in the traceback.

    Design note: reading a frame variable depends on the SDK's internals, so it can stop working
    after an SDK upgrade; then it returns None and the cost of that call is simply not counted
    (a test and a live check catch this). The alternatives were rejected: calling the raw
    `create` endpoint and parsing ourselves would change the request that every measurement was
    made with, and an HTTP hook would add a second, hidden code path.

    Returns:
        The usage, or None if no response with a usage is found.
    """
    traceback = error.__traceback__
    while traceback is not None:
        candidate = traceback.tb_frame.f_locals.get("response")
        sdk_usage = getattr(candidate, "usage", None)
        if sdk_usage is not None and hasattr(sdk_usage, "input_tokens"):
            return _usage_of(sdk_usage)
        traceback = traceback.tb_next
    return None
