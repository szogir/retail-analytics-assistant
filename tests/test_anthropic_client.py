"""Tests of the Claude adapter with a stub SDK client (no network, no key)."""

import json
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from retail_assistant.config import PROJECT_ROOT
from retail_assistant.llm.anthropic_client import AnthropicClient, output_format
from retail_assistant.llm.base import LLMOutputError, LLMProviderError
from retail_assistant.llm.profiles import ModelProfile, load_profile
from retail_assistant.llm.schemas import SqlAnswer

ANSWER = SqlAnswer(language="hu", intent="metric_query", approach="r", sql="SELECT 1")


class StubMessages:
    """Replaces `client.messages`: records the request and returns / raises what it is told.

    The adapter calls `messages.with_raw_response.create(...).parse()`; the stub mimics that
    chain, so `with_raw_response` is the stub itself.
    """

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.request: dict[str, Any] = {}
        self.with_raw_response = self

    def create(self, **request: Any) -> Any:
        self.request = request
        if self.error:
            raise self.error
        return SimpleNamespace(parse=lambda: self.response)


def response(text: str | None = None, stop_reason: str = "end_turn") -> Any:
    """A fake Messages API answer; `text` defaults to the JSON of `ANSWER`."""
    usage = SimpleNamespace(
        input_tokens=100,
        output_tokens=40,
        cache_creation_input_tokens=10,
        cache_read_input_tokens=500,
    )
    body = ANSWER.model_dump_json() if text is None else text
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=body)], stop_reason=stop_reason, usage=usage
    )


def make_client(messages: StubMessages, profile: ModelProfile) -> AnthropicClient:
    sdk = SimpleNamespace(messages=messages)
    return AnthropicClient(profile, sdk_client=sdk)  # type: ignore[arg-type]


@pytest.fixture
def small() -> ModelProfile:
    return load_profile(PROJECT_ROOT / "config" / "models.yaml", "claude_small")


@pytest.fixture
def mid() -> ModelProfile:
    return load_profile(PROJECT_ROOT / "config" / "models.yaml", "claude_mid")


def test_success_maps_output_and_usage(small: ModelProfile) -> None:
    messages = StubMessages(response())
    result = make_client(messages, small).generate("SYSTEM", "USER", SqlAnswer, max_tokens=900)

    assert result.output == ANSWER
    assert result.provider == "anthropic"
    assert result.model == small.model
    # Cache writes (10) and cache reads (500) are reported separately from normal input (100).
    assert (result.usage.input_tokens, result.usage.cached_input_tokens) == (100, 500)
    assert result.usage.cache_creation_input_tokens == 10
    assert result.usage.output_tokens == 40
    assert result.latency_ms >= 0

    request = messages.request
    assert request["model"] == small.model
    assert request["max_tokens"] == 900
    assert request["output_config"] == {"format": output_format(SqlAnswer)}
    assert request["messages"] == [{"role": "user", "content": "USER"}]
    # The stable system prompt is marked cacheable.
    assert request["system"][0]["text"] == "SYSTEM"
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_temperature_is_sent_only_to_models_that_accept_it(
    small: ModelProfile, mid: ModelProfile
) -> None:
    accepting = StubMessages(response())
    make_client(accepting, small).generate("s", "u", SqlAnswer, temperature=0.0)
    assert accepting.request["extra_body"] == {"temperature": 0.0}

    rejecting = StubMessages(response())
    make_client(rejecting, mid).generate("s", "u", SqlAnswer, temperature=0.0)
    assert "extra_body" not in rejecting.request
    # The profile's own request options (here: thinking) are merged into the call.
    assert rejecting.request["thinking"] == mid.request_options["thinking"]


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_refused_and_truncated_calls_are_output_errors_with_their_usage(
    small: ModelProfile, stop_reason: str
) -> None:
    messages = StubMessages(response(text="{", stop_reason=stop_reason))
    with pytest.raises(LLMOutputError) as caught:
        make_client(messages, small).generate("s", "u", SqlAnswer)
    # The stop reason is the reported cause, not "does not match" (truncated JSON is invalid).
    assert "does not match" not in str(caught.value)
    assert caught.value.usage is not None and caught.value.usage.output_tokens == 40


@pytest.mark.parametrize("text", ["{", "not json at all", json.dumps({"language": "de"}), ""])
def test_unusable_answers_keep_the_billed_usage(small: ModelProfile, text: str) -> None:
    """Invalid JSON or a schema mismatch is an output error, and its tokens were billed."""
    with pytest.raises(LLMOutputError, match="does not match") as caught:
        make_client(StubMessages(response(text=text)), small).generate("s", "u", SqlAnswer)
    usage = caught.value.usage
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens) == (100, 40)
    assert usage.cache_creation_input_tokens == 10 and usage.cached_input_tokens == 500
    assert caught.value.latency_ms >= 0


def test_api_failures_are_provider_errors(small: ModelProfile) -> None:
    request = httpx2.Request("POST", "https://example.invalid")
    error = anthropic.APIConnectionError(request=request)
    with pytest.raises(LLMProviderError):
        make_client(StubMessages(error=error), small).generate("s", "u", SqlAnswer)
