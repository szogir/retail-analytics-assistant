# Retail Analytics Assistant

A small, **evaluated** text-to-SQL assistant: business users ask questions about a
(synthetic) discount-retail chain in English or Hungarian, and get an answer that
shows **which SQL ran, which metric definition was used and which assumptions were made**.

> Status: work in progress. Naive and metadata-commented evaluation modes work.
> The 50 development and 50 held-out cases are independently checked candidates awaiting
> personal review and freezing. Semantic metrics, the SQL validator and per-user views
> are not implemented yet. Historical reports use the original 28-case suite.

## Intended demonstration

- **Accuracy you can measure** - a golden test set and an evaluation runner that compares
  query *results* (execution accuracy), not SQL text.
- **A semantic layer** *(planned)* - metric definitions in YAML, so "net sales" means the same thing
  in every answer.
- **Permissions enforced in the backend** *(planned)* - the model never decides what a user may see;
  queries run against per-user filtered views.
- **Safety by design** *(planned)* - generated SQL is parsed and validated (read-only, allow-listed
  tables) before execution.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                       # install dependencies
uv run pytest                 # run the unit tests
cp .env.example .env          # then add your ANTHROPIC_API_KEY
```

More commands (data generation, evaluation, CLI) will be documented as they are added.

The [evaluation protocol](docs/decisions.md#8-preregistered-evaluation-protocol-2026-10-04)
defines the primary metric and paired analysis before semantic development.
The [shared business contract](docs/business_contract.md) contains the rules available
to implementation. See [evaluation operation](docs/evaluation.md) for offline validation,
human approval and release commands. Default checks do not read sealed cases.

## Project layout

```text
src/retail_assistant/   application code
tests/                  unit tests (no network, no API key needed)
docs/decisions.md       design decisions and the alternatives considered
```

## Limitations

This is a demo, not a production system. A dedicated section will list what is
missing for production use and how it would be addressed.

- **Synthetic, scaled-down data.** The dataset is fictional and shaped like discount
  retail. Volumes are deliberately small (about 11 receipts per store per day, roughly
  1.4 million euro of sales per year for the whole chain) so that everything runs in
  seconds. VAT rates, prices and holidays are simplified and are not tax-law or calendar
  references. Real data is noisier, so measured accuracy is an upper estimate.

## License

MIT - see [LICENSE](LICENSE).
