"""Application settings: where the database, the config folder and the API key come from.

What it does: collects every environment-dependent value in one validated object.

Why it exists: the rest of the code must not read environment variables or hard-code paths.
One `Settings` object makes it obvious what can be configured, and tests can build their own
instance with temporary paths.

Where it sits in the pipeline: used by the model factory and the CLI / eval runner, i.e.
before the first step (context building).
"""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/retail_assistant/config.py -> parents[0] = retail_assistant, [1] = src, [2] = repo root
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Settings read from environment variables (and from a local `.env` file).

    Attributes:
        db_path: The DuckDB file with the synthetic data (env: RETAIL_DB_PATH).
        config_dir: Folder with models.yaml, users.yaml and the prompts (RETAIL_CONFIG_DIR).
        semantic_dir: Folder with the semantic layer YAML files (RETAIL_SEMANTIC_DIR).
        model_profile: Name of the default profile in models.yaml (RETAIL_MODEL_PROFILE).
        anthropic_api_key: API key (env: ANTHROPIC_API_KEY). Optional here, because the
            Anthropic SDK can also find credentials by itself.
    """

    # Design note: pydantic-settings instead of os.environ.get(...) calls scattered around:
    # the values are typed, validated once, and `SecretStr` keeps the key out of logs and
    # tracebacks (printing it shows '**********').
    model_config = SettingsConfigDict(
        env_prefix="RETAIL_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    db_path: Path = PROJECT_ROOT / "data" / "retail.duckdb"
    config_dir: Path = PROJECT_ROOT / "config"
    semantic_dir: Path = PROJECT_ROOT / "semantic"
    model_profile: str = "claude_small"
    # The alias bypasses the RETAIL_ prefix: the key keeps its standard name.
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
