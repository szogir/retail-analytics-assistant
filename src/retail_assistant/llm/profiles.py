"""Model profiles: which model to call, what it costs, and which request options it needs.

What it does: loads `config/models.yaml` into validated objects and turns token counts into
a dollar cost.

Why it exists: model names and prices change often. Keeping them in a YAML file (with a
date next to the prices) means the code never hard-codes either, and every eval report can
state exactly which profile produced its numbers.

Where it sits in the pipeline: configuration for the SQL generation step; the cost figure
feeds the eval report.
"""

import datetime as dt
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from retail_assistant.llm.base import Usage

_PER_MILLION = 1_000_000


class ModelProfile(BaseModel):
    """One entry of `config/models.yaml`.

    Attributes:
        name: Profile name (the key in the YAML file), filled in by the loader.
        provider: Which adapter to use ("anthropic").
        model: Exact model name sent to the provider.
        price_date: The date the prices were checked. Prices go stale, so it is stored.
        input_per_mtok: USD per million input tokens.
        cached_input_per_mtok: USD per million input tokens served from the prompt cache.
        output_per_mtok: USD per million output tokens.
        supports_temperature: False for models that reject a temperature parameter.
        request_options: Extra request fields merged into every call.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = ""
    provider: str
    model: str
    price_date: dt.date
    input_per_mtok: float
    cached_input_per_mtok: float
    output_per_mtok: float
    supports_temperature: bool = True
    request_options: dict[str, Any] = {}

    def cost_usd(self, usage: Usage) -> float:
        """Return the price of one call in US dollars.

        Args:
            usage: Token counts of the call.

        Returns:
            Cost in USD, calculated from the per-million prices of this profile.
        """
        return (
            usage.input_tokens * self.input_per_mtok
            + usage.cached_input_tokens * self.cached_input_per_mtok
            + usage.output_tokens * self.output_per_mtok
        ) / _PER_MILLION


def load_profile(models_file: Path, name: str) -> ModelProfile:
    """Load one profile from the models file.

    Args:
        models_file: Path of `config/models.yaml`.
        name: Profile name, e.g. "claude_small".

    Returns:
        The validated profile.

    Raises:
        FileNotFoundError: If the models file does not exist.
        KeyError: If the profile name is not in the file (the message lists the valid names).
        pydantic.ValidationError: If the entry does not match the model.
    """
    raw = yaml.safe_load(models_file.read_text(encoding="utf-8"))
    profiles: dict[str, Any] = raw["profiles"]
    if name not in profiles:
        raise KeyError(f"unknown model profile '{name}'; available: {sorted(profiles)}")
    return ModelProfile.model_validate({**profiles[name], "name": name})
