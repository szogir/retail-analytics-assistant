# Design decisions

Short records of the main decisions: the context, what was decided, the
alternatives that were considered, and the consequences.

---

## 1. Local DuckDB instead of a cloud data platform

**Context.** The demo must run on any machine with a single command, so a reviewer
can clone it and try it in minutes. At the same time the SQL should feel like a
modern analytical platform.

**Decision.** Use DuckDB with a single database file, opened read-only.

**Alternatives considered.**
- *PostgreSQL* - has real row-level security, but needs a running server and is an OLTP engine.
- *SQLite* - zero setup, but weak analytical SQL.
- *A managed lakehouse (e.g. Databricks)* - closest to a real enterprise setup, but not
  reproducible without an account.

**Consequences.** DuckDB has no built-in row-level security, so permissions are
simulated with per-user filtered views (see decision 3 once added). In production
this would be handled by the data platform itself, using the end user's identity.

---

## 2. A thin, own LLM interface instead of an agent framework

**Context.** The pipeline is a short, fixed sequence of steps. Each step should be
testable on its own, and the model provider should be replaceable.

**Decision.** Define a small `LLMClient` protocol and implement one adapter per
provider using the official SDKs. No LangChain / LlamaIndex.

**Alternatives considered.**
- *LangChain / LangGraph* - many ready components and agent state machines, but more
  abstraction than a four-step chain needs.
- *LiteLLM* - one call signature for many providers, but hides provider-specific
  behaviour (structured output, prompt caching) that matters here.
- *Pydantic AI* - a good, typed, model-agnostic option; the main alternative if the
  own layer grows.

**Consequences.** Slightly more code to write, but every step is visible, testable
with a fake client, and swappable through configuration.

---

## 3. Command-line interface first, API and UI later

**Context.** The available time is short. The most valuable evidence is measured
accuracy and enforced permissions, not a polished interface.

**Decision.** Ship a CLI (`typer` + `rich`) that calls the pipeline directly.

**Alternatives considered.**
- *FastAPI + Streamlit* - the target architecture, but it would take time away from
  evaluation and safety work.
- *Notebook demo* - fast, but not testable or operable.

**Consequences.** The pipeline is a plain function with a clean boundary, so an API
layer can be added without changing it.

---

## 4. Synthetic data with a shifted fiscal year

**Context.** The project must show that a semantic layer measurably improves accuracy.
That needs data where the correct answer is known and where the classic traps exist on
purpose. Real or public retail data cannot guarantee that, and has licence limits.

**Decision.** Generate fictional data with a fixed seed. Conventions:
- The fiscal year starts on 1 March and is named after the calendar year in which it
  starts (2025-03-01 .. 2026-02-28 is fiscal year 2025). `fiscal_month` is 1..12 with
  March = 1. `fiscal_week` counts 7-day blocks from the fiscal year start (1..53).
- VAT rates differ by country and product category. They are simplified and are not
  tax-law references.
- The catalogue and the store list are fixed tables, only base prices are random.

**Alternatives considered.**
- *Public datasets* - no known traps, no two-currency or per-store structure.
- *Faker-generated names* - unrealistic names, no matching EN/HU pairs, extra dependency.
- *Fiscal year = calendar year* - the `fiscal_*` columns would add nothing to test.

**Consequences.** Measured accuracy is an upper estimate: real data is noisier. This
goes into the README limitations.

---

## 5. Several years of data, closed days and a holiday table

**Context.** One year of data cannot support year-over-year questions, and a store that
trades every day of the year is unrealistic. Both change which answers are correct.

**Decision.**
- The data covers 2023-03-01 to 2026-10-03: three full fiscal years and a part of the
  current one. Volume grows 4% and prices 3% per year.
- Stores have no sales rows on public holidays; Austrian stores are also closed on
  Sundays (a trading rule). Hungarian stores are open on Sundays.
- The holiday list is also stored in `dim_holiday` (country, date, name), generated from
  the same function that closes the stores, so the two cannot disagree. Easter-based
  holidays are computed, not typed in.
- `fx_rate.eur_rate` means "units of the currency per 1 EUR"; to convert to euro, divide.
  The HUF rate follows a mean-reverting walk around 370 within +-12.
- Facts are built with vectorised numpy and bulk-loaded through a temporary Parquet file.

**Alternatives considered.**
- *Holidays only inside the generator* - the correct answer to "how many holidays" would
  then be unreachable from SQL, and the semantic layer would have nothing to describe.
- *`pyarrow` for direct DataFrame loading* - an extra dependency; the Parquet round trip
  takes a fraction of a second for 1.5 million rows.
- *Renaming `eur_rate` to `units_per_eur`* - clearer, but the name stays as specified;
  the direction is documented in the DDL, the generator and the tests instead.

**Consequences.** "Average per day" has two valid readings (calendar days vs trading
days), which is a deliberate trap. The incomplete fiscal year 2026 must not be compared
with a full year. Holiday dates are a simplified national list (no bridge days).

---

## 6. Evaluate in three steps: schema, schema with comments, semantic layer

**Context.** A column such as `eur_rate` is easy to misread: multiplying instead of
dividing turns 0.79 million euro of Hungarian sales into 109,469 million. If the baseline
sees only the column name, it fails for a reason a one-line comment would remove, and the
semantic layer would get credit for what plain metadata can do.

**Decision.** The database carries column comments (real metadata, no business rules).
The evaluation compares three modes: `naive` (names and types only), `commented`
(plus the column comments) and `semantic` (metrics, join paths, examples).

**Alternatives considered.** Two modes only (naive vs semantic) - a bigger headline
number, but an unfair baseline.

**Consequences.** One more mode in the context builder and in the report. The semantic
layer still has to show a gain over the commented baseline, which is the more honest claim.

## 7. Metric conventions used by the golden set

- Net sales = gross - discount - VAT, converted with the rate of the sales day, excluding
  cancelled receipts and the test store. Returns are negative lines and reduce net sales.
- Receipt count and average basket count SALES receipts only (no return receipts, no
  cancelled receipts); the basket is net sales of those receipts divided by their count.
- A bare year ("in 2025") means the calendar year. Only the word "fiscal" selects the
  fiscal year (March to February).
- Average per day divides by trading days (days with sales), not by calendar days.

## 8. Preregistered evaluation protocol (2026-10-04)

**Timing.** This protocol and both candidate suites are authored before semantic-layer
implementation. Human review is pending; neither candidate is represented as approved
or frozen until its release gate passes. The final manifest records all case content and
review metadata, raw YAML hashes, reference-check code and database identity. A local
timestamp/hash proves content identity, not an independently witnessed creation date.

**Suites.** 50 development cases and 50 held-out cases, each with EN/HU wording. Each
contains 40 result cases, five clarification cases, four security cases and one unrelated
request. Ten result cases per suite require documented defaults and explicit assumptions.
The existing 28 development cases remain in development. All 80 result references must
agree with independently written DataFrame arithmetic. No merely executable SQL counts
as sufficient reference validation. The owner reviews all 100 cases personally.

**Primary outcome.** Execution accuracy on the 40 result cases in each suite, allowing
extra columns but using relative numeric tolerance 1e-6 and absolute tolerance 1e-9.
An incorrect refusal, clarification, SQL/provider failure or truncated result scores zero.
A truncated reference aborts the run. Both languages have equal weight within a case;
all cases have equal weight. NULL, empty results and zero are distinct.

**Secondary outcomes.** Original strict accuracy (exact column count), original lenient
accuracy (1% tolerance), accuracy by language/category, required-answer cases with stated
assumptions, justified clarifications, refusals, latency and actual recorded cost. The
assumption check is a lexical proxy and never changes the numerical primary outcome.
Security is reported separately; until backend enforcement exists, this is refusal
behaviour only. Permission-specific cases will form a separate versioned suite later.

**Repeated runs.** After approval and freezing, run the naive development baseline three
times with the same model/profile, temperature, output limit, database and cases. Report
all runs, their mean, range and sample standard deviation; do not select the best run.
Freeze prompts, model configuration, scoring and semantic files before revealing holdout
results. On holdout, run naive, commented and semantic modes three times each, both
languages, with no omitted cases: 900 model requests. The old 28-case result is historical
and must not be compared numerically with the enlarged suite.

**Confirmatory comparison.** Semantic minus commented primary accuracy is the main
comparison; semantic minus naive is a secondary descriptive comparison. For each result
case, average its six outcomes (two languages, three repetitions) per mode, then take the
paired difference. Resample the 40 case differences with replacement, 10,000 bootstrap
samples, seed 42. Report the mean difference and two-sided percentile 95% interval. Do
not resample translations or repeats as independent observations. The bootstrap assumes
case-level exchangeability; shared templates/schema and manual selection limit broader
generalisation. It is not a confidence guarantee for arbitrary real-world questions.

**Success rule.** Claim a material semantic benefit only if semantic minus commented on
holdout is at least +10 percentage points and its 95% interval lower bound is above zero.
Report naive comparison and all secondary metrics even when the rule fails. Do not change
the threshold, choose a favourable language/model or drop cases after seeing results.
Development noise is diagnostic, not a significance threshold. Security must pass every
security case in every repetition before claiming that the tested safety behaviour passed.

**Failures and changes.** Keep failures in the denominator. A run interrupted before all
requests finish is incomplete and cannot enter confirmatory analysis. No selective retry
of failed questions. Any full rerun must be identified, with the reason recorded. Correct
a genuinely wrong reference by a new suite version and rerun all compared modes; never
silently rewrite the old manifest or baseline. Holdout-informed development turns that
suite into regression data, so a new unseen suite is needed for another confirmatory claim.

**Isolation.** All sealed YAML, arithmetic and detailed outputs stay under `evals/holdout/`.
Normal tests and static checks exclude that directory. Development uses the public
business contract and development cases only. Local read-deny rules reduce accidental
exposure but are not an OS-level boundary against arbitrary subprocess reads; a separate
development checkout without the holdout is the stronger isolation option.
