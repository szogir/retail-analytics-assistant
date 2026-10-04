"""Factory: builds the right `LLMClient` from a profile name.

What it does: reads the profile from `config/models.yaml` and returns the matching client
together with the profile (the profile is needed for the cost calculation).

Why it exists: callers (CLI, eval runner) say "give me claude_small" and never learn which
adapter class or model name is behind it.

Where it sits in the pipeline: wiring step before SQL generation.
"""

from dataclasses import dataclass

from retail_assistant.config import Settings
from retail_assistant.llm.anthropic_client import AnthropicClient
from retail_assistant.llm.base import LLMClient
from retail_assistant.llm.profiles import ModelProfile, load_profile


@dataclass(frozen=True)
class LLMSetup:
    """A ready client and the profile it was built from."""

    client: LLMClient
    profile: ModelProfile


def create_llm(settings: Settings, profile_name: str | None = None) -> LLMSetup:
    """Build the client for a profile.

    Args:
        settings: Application settings (config folder, default profile, API key).
        profile_name: Profile to use; the default from the settings if None.

    Returns:
        The client and its profile.

    Raises:
        KeyError: If the profile does not exist.
        ValueError: If the profile names an unsupported provider.
    """
    profile = load_profile(
        settings.config_dir / "models.yaml", profile_name or settings.model_profile
    )
    if profile.provider == "anthropic":
        key = settings.anthropic_api_key
        client = AnthropicClient(profile, api_key=key.get_secret_value() if key else None)
        return LLMSetup(client=client, profile=profile)
    raise ValueError(f"unsupported provider '{profile.provider}' in profile '{profile.name}'")
