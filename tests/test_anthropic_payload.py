"""The adapter's request is byte-identical to the one the SDK's `messages.parse()` sends.

Why this test exists: every published measurement was made with `parse()`. The adapter now calls
`create()` and validates the JSON itself (to keep the usage of an unusable answer). That is only
acceptable if the model receives exactly the same request body. The test sends both calls
through a fake HTTP transport (no network) and compares the raw bytes. If an SDK upgrade changes
what `parse()` sends, this test fails.
"""

import json
from typing import Any

import anthropic
import httpx2
import pytest

from retail_assistant.config import PROJECT_ROOT
from retail_assistant.llm.anthropic_client import AnthropicClient
from retail_assistant.llm.profiles import load_profile
from retail_assistant.llm.schemas import SqlAnswer

ANSWER = SqlAnswer(language="en", intent="metric_query", approach="a", sql="SELECT 1")
FAKE_RESPONSE = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "m",
    "content": [{"type": "text", "text": ANSWER.model_dump_json()}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    },
}


@pytest.mark.parametrize("profile_name", ["claude_small", "claude_mid"])
def test_create_sends_the_same_body_as_parse(profile_name: str) -> None:
    profile = load_profile(PROJECT_ROOT / "config" / "models.yaml", profile_name)
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(200, json=FAKE_RESPONSE)

    sdk = anthropic.Anthropic(
        api_key="unused", http_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    )

    # The request as it was made before: the SDK's parse().
    old: dict[str, Any] = {
        "model": profile.model,
        "max_tokens": 4096,
        "system": [{"type": "text", "text": "SYSTEM", "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": "USER"}],
        "output_format": SqlAnswer,
    }
    if profile.supports_temperature:
        old["extra_body"] = {"temperature": 0.0}
    old.update(profile.request_options)
    sdk.messages.parse(**old)

    # The request as it is made now: the adapter.
    AnthropicClient(profile, sdk_client=sdk).generate("SYSTEM", "USER", SqlAnswer, max_tokens=4096)

    parse_request, adapter_request = captured
    assert adapter_request.content == parse_request.content
    assert adapter_request.url == parse_request.url
    assert adapter_request.method == parse_request.method
    assert json.loads(adapter_request.content)["output_config"]["format"]["type"] == "json_schema"
    # Only the SDK's own telemetry headers may differ.
    differing = {
        name
        for name in set(parse_request.headers) | set(adapter_request.headers)
        if parse_request.headers.get(name) != adapter_request.headers.get(name)
    }
    assert differing <= {"x-stainless-helper", "x-stainless-raw-response"}
