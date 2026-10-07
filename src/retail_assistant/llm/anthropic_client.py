"""Claude adapter: implements `LLMClient` with the official Anthropic SDK.

What it does: sends one request to the Messages API and returns the answer already parsed
into the requested Pydantic model (structured output), with token usage and latency. The
tokens of an unusable answer (refused, truncated, not valid JSON) are reported too.

Why it exists: it is the only module that knows about the Anthropic SDK. Everything else
talks to the `LLMClient` protocol.

Where it sits in the pipeline: SQL generation step.
"""

import time
from typing import Any

import anthropic
from pydantic import BaseModel, TypeAdapter, ValidationError

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
            "output_config": {"format": output_format(schema)},
        }
        # Design note: the profile says whether the model accepts a temperature (the newest
        # models reject it); if so it goes in as an extra body field. The alternative, always
        # sending it, would break those models.
        if self._profile.supports_temperature:
            request["extra_body"] = {"temperature": temperature}
        request.update(self._profile.request_options)

        # Design note: the raw `create` call plus our own validation, instead of the SDK's
        # `messages.parse()`. `parse()` downloads and validates in one step and raises on invalid
        # JSON WITHOUT handing over the response, so the billed tokens of an unusable answer were
        # lost. The request body is byte-identical to the one `parse()` sends
        # (`tests/test_anthropic_payload.py` compares them through a fake transport); only the
        # SDK's own telemetry headers differ. The alternative, reading the response out of the
        # SDK's traceback, relied on SDK internals and was rejected.
        started = time.perf_counter()
        try:
            message = self._client.messages.with_raw_response.create(**request).parse()
        except anthropic.APIError as exc:
            raise LLMProviderError(f"Anthropic API call failed: {exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        usage = _usage_of(message.usage)

        # Order matters: a truncated or refused answer is not valid JSON, and the stop reason
        # tells the true cause.
        if message.stop_reason == "refusal":
            raise LLMOutputError("the model refused to answer", usage, latency_ms)
        if message.stop_reason == "max_tokens":
            raise LLMOutputError(f"output cut off at max_tokens={max_tokens}", usage, latency_ms)
        text = "".join(block.text for block in message.content if block.type == "text")
        try:
            output = schema.model_validate_json(text)
        except ValidationError as exc:
            raise LLMOutputError(
                f"model output does not match {schema.__name__}: {exc}", usage, latency_ms
            ) from exc

        return LLMResult(
            output=output,
            usage=usage,
            latency_ms=latency_ms,
            provider="anthropic",
            model=self._profile.model,
        )


def output_format(schema: type[BaseModel]) -> dict[str, Any]:
    """Build the JSON-schema output format exactly as the SDK's `parse()` builds it.

    Why the key order (schema before type): the request body is serialized in dict order, and
    the equality test with `parse()` compares bytes.
    """
    json_schema = TypeAdapter(schema).json_schema()
    return {"schema": anthropic.transform_schema(json_schema), "type": "json_schema"}


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
