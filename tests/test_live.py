"""Live smoke test: one real call to the model. Excluded by default.

Run it with `uv run pytest -m live`. It needs an API key (ANTHROPIC_API_KEY in the
environment or in the local .env file) and costs a fraction of a cent.
"""

import pytest

from retail_assistant.config import Settings
from retail_assistant.llm.factory import create_llm
from retail_assistant.llm.schemas import SqlAnswer

pytestmark = pytest.mark.live


@pytest.mark.parametrize("profile", ["claude_small", "claude_mid"])
def test_a_real_model_returns_a_valid_structured_answer(profile: str) -> None:
    setup = create_llm(Settings(), profile)
    result = setup.client.generate(
        system="You write DuckDB SQL. Table: dim_store(store_id INTEGER, store_name VARCHAR).",
        user="Question language: en\nQuestion: How many stores are there?",
        schema=SqlAnswer,
        max_tokens=1024,
    )
    assert result.output.intent in ("metric_query", "definition", "out_of_scope")
    assert result.output.sql.strip().upper().startswith("SELECT")
    assert result.usage.output_tokens > 0
    assert setup.profile.cost_usd(result.usage) > 0
