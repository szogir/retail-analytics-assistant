"""Tests for the LLM interface pieces that need no network: fake client, profiles, factory."""

import datetime as dt
from pathlib import Path

import pytest

from retail_assistant.config import PROJECT_ROOT, Settings
from retail_assistant.llm.anthropic_client import AnthropicClient
from retail_assistant.llm.base import LLMClient, LLMOutputError, LLMProviderError, Usage
from retail_assistant.llm.factory import create_llm
from retail_assistant.llm.fake import FakeLLMClient
from retail_assistant.llm.profiles import load_profile
from retail_assistant.llm.schemas import SqlAnswer

MODELS_FILE = PROJECT_ROOT / "config" / "models.yaml"


def make_answer(sql: str = "SELECT 1") -> SqlAnswer:
    return SqlAnswer(language="en", intent="metric_query", approach="r", sql=sql)


def test_fake_returns_scripted_answers_in_order_and_records_calls() -> None:
    first, second = make_answer("SELECT 1"), make_answer("SELECT 2")
    fake = FakeLLMClient(responses=[first, second])
    client: LLMClient = fake  # the fake must satisfy the protocol

    result = client.generate("sys", "usr", SqlAnswer, temperature=0.0, max_tokens=77)
    assert result.output is first
    assert (result.provider, result.model) == ("fake", "fake-model")
    assert client.generate("sys2", "usr2", SqlAnswer).output is second
    assert [(c.system, c.user) for c in fake.calls] == [("sys", "usr"), ("sys2", "usr2")]
    assert fake.calls[0].max_tokens == 77


def test_fake_raises_scripted_errors_and_fails_loudly_when_empty() -> None:
    fake = FakeLLMClient(responses=[LLMOutputError("bad json"), LLMProviderError("down")])
    with pytest.raises(LLMOutputError):
        fake.generate("s", "u", SqlAnswer)
    with pytest.raises(LLMProviderError):
        fake.generate("s", "u", SqlAnswer)
    with pytest.raises(AssertionError, match="no more scripted"):
        fake.generate("s", "u", SqlAnswer)


def test_fake_responder_sees_the_prompts() -> None:
    fake = FakeLLMClient(responder=lambda system, user: make_answer(f"SELECT '{user}'"))
    assert fake.generate("s", "hello", SqlAnswer).output.sql == "SELECT 'hello'"


def test_fake_needs_exactly_one_source_of_answers() -> None:
    with pytest.raises(ValueError):
        FakeLLMClient()
    with pytest.raises(ValueError):
        FakeLLMClient(responses=[], responder=lambda s, u: make_answer())


def test_both_profiles_exist_with_dated_prices() -> None:
    for name in ("claude_mid", "claude_small"):
        profile = load_profile(MODELS_FILE, name)
        assert profile.name == name
        assert profile.provider == "anthropic"
        assert profile.model  # the model name is in the YAML, not in the code
        assert isinstance(profile.price_date, dt.date)
        assert profile.cached_input_per_mtok < profile.input_per_mtok < profile.output_per_mtok


def test_cost_is_calculated_from_per_million_prices() -> None:
    profile = load_profile(MODELS_FILE, "claude_small")
    usage = Usage(input_tokens=2_000_000, output_tokens=1_000_000, cached_input_tokens=1_000_000)
    expected = (
        2 * profile.input_per_mtok + 1 * profile.output_per_mtok + profile.cached_input_per_mtok
    )
    assert profile.cost_usd(usage) == pytest.approx(expected)
    assert profile.cost_usd(Usage(0, 0)) == 0


def test_unknown_profile_lists_the_valid_names() -> None:
    with pytest.raises(KeyError, match="claude_small"):
        load_profile(MODELS_FILE, "does_not_exist")


def test_factory_builds_the_claude_adapter_without_network(tmp_path: Path) -> None:
    settings = Settings(config_dir=PROJECT_ROOT / "config", anthropic_api_key="test-key")  # type: ignore[arg-type]
    setup = create_llm(settings, "claude_mid")
    assert isinstance(setup.client, AnthropicClient)
    assert setup.profile.name == "claude_mid"
    assert create_llm(settings).profile.name == settings.model_profile


def test_factory_rejects_an_unsupported_provider(tmp_path: Path) -> None:
    (tmp_path / "models.yaml").write_text(
        "profiles:\n  x:\n    provider: other\n    model: m\n    price_date: 2026-01-01\n"
        "    input_per_mtok: 1\n    cached_input_per_mtok: 1\n"
        "    cache_write_per_mtok: 1\n    output_per_mtok: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported provider"):
        create_llm(Settings(config_dir=tmp_path), "x")


def test_the_api_key_is_never_printed() -> None:
    settings = Settings(anthropic_api_key="sk-secret-value")  # type: ignore[arg-type]
    assert "sk-secret-value" not in repr(settings)
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-secret-value"


def test_cache_writes_are_priced_separately_from_normal_input() -> None:
    profile = load_profile(MODELS_FILE, "claude_small")
    usage = Usage(input_tokens=0, output_tokens=0, cache_creation_input_tokens=1_000_000)
    assert profile.cost_usd(usage) == pytest.approx(profile.cache_write_per_mtok)
    assert profile.cache_write_per_mtok > profile.input_per_mtok


def test_the_thinking_settings_of_both_profiles_mean_no_thinking() -> None:
    # The model comparison must differ only in the model: small sends no thinking field; for
    # mid the API accepts only `between_tools` as the "off" value (it rejects `disabled`).
    assert load_profile(MODELS_FILE, "claude_small").thinking_setting == "not sent (model default)"
    assert load_profile(MODELS_FILE, "claude_mid").thinking_setting == "between_tools"
