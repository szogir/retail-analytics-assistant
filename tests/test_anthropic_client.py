"""Tests of the Claude adapter with a stub SDK client (no network, no key)."""

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import BaseModel, ValidationError

from retail_assistant.config import PROJECT_ROOT
from retail_assistant.llm.anthropic_client import AnthropicClient
from retail_assistant.llm.base import LLMOutputError, LLMProviderError
from retail_assistant.llm.profiles import ModelProfile, load_profile
from retail_assistant.llm.schemas import SqlAnswer

ANSWER = SqlAnswer(language="hu", intent="metric_query", approach="r", sql="SELECT 1")


class StubMessages:
    """Replaces `client.messages`: records the request and returns / raises what it is told."""

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.request: dict[str, Any] = {}

    def parse(self, **request: Any) -> Any:
        self.request = request
        if self.error:
            raise self.error
        return self.response


def response(parsed: BaseModel | None = ANSWER, stop_reason: str = "end_turn") -> Any:
    usage = SimpleNamespace(
        input_tokens=100,
        output_tokens=40,
        cache_creation_input_tokens=10,
        cache_read_input_tokens=500,
    )
    return SimpleNamespace(parsed_output=parsed, stop_reason=stop_reason, usage=usage)


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

    assert result.output is ANSWER
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
    assert request["output_format"] is SqlAnswer
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
def test_refusal_and_truncation_are_output_errors(small: ModelProfile, stop_reason: str) -> None:
    messages = StubMessages(response(stop_reason=stop_reason))
    with pytest.raises(LLMOutputError):
        make_client(messages, small).generate("s", "u", SqlAnswer)


def test_missing_parsed_output_is_an_output_error(small: ModelProfile) -> None:
    with pytest.raises(LLMOutputError, match="no parsed"):
        make_client(StubMessages(response(parsed=None)), small).generate("s", "u", SqlAnswer)


def test_schema_mismatch_is_an_output_error(small: ModelProfile) -> None:
    try:
        SqlAnswer.model_validate({"language": "de"})
    except ValidationError as exc:
        error = exc
    with pytest.raises(LLMOutputError, match="does not match"):
        make_client(StubMessages(error=error), small).generate("s", "u", SqlAnswer)


def test_api_failures_are_provider_errors(small: ModelProfile) -> None:
    request = httpx2.Request("POST", "https://example.invalid")
    error = anthropic.APIConnectionError(request=request)
    with pytest.raises(LLMProviderError):
        make_client(StubMessages(error=error), small).generate("s", "u", SqlAnswer)


def test_usage_of_a_response_that_does_not_fit_the_schema_is_still_recorded(
    small: ModelProfile,
) -> None:
    """The SDK raises while parsing; the billed tokens must survive in the error."""

    class ParsingMessages:
        def parse(self, **request: Any) -> Any:
            def sdk_parser(response: Any) -> Any:  # mimics the SDK frame that holds the response
                SqlAnswer.model_validate({"language": "de"})
                return response

            return sdk_parser(response(parsed=None))

    with pytest.raises(LLMOutputError, match="does not match") as caught:
        make_client(ParsingMessages(), small).generate("s", "u", SqlAnswer)  # type: ignore[arg-type]
    usage = caught.value.usage
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens) == (100, 40)
    assert usage.cache_creation_input_tokens == 10 and usage.cached_input_tokens == 500
    assert caught.value.latency_ms >= 0


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_refused_and_truncated_calls_keep_their_usage(
    small: ModelProfile, stop_reason: str
) -> None:
    messages = StubMessages(response(stop_reason=stop_reason))
    with pytest.raises(LLMOutputError) as caught:
        make_client(messages, small).generate("s", "u", SqlAnswer)
    assert caught.value.usage is not None and caught.value.usage.output_tokens == 40


def test_without_a_recoverable_response_the_usage_is_none(small: ModelProfile) -> None:
    try:
        SqlAnswer.model_validate({"language": "de"})
    except ValidationError as exc:
        error = exc
    with pytest.raises(LLMOutputError) as caught:
        make_client(StubMessages(error=error), small).generate("s", "u", SqlAnswer)
    assert caught.value.usage is None
