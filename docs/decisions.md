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

## 9. External holdout with a public hash commitment

**Context.** A directory inside the working tree remains discoverable by searches,
subprocesses and development tooling. File-tool deny rules alone are insufficient.

**Decision.** Keep the entire holdout outside the repository during development,
including independent calculators, worksheets, backups and per-case results. Only
the owner's evaluation environment supplies `HOLDOUT_DIR` or `--holdout-dir`; there
is no internal default. Missing configuration or an empty suite fails explicitly.
CI skips the external checks when the variable is unset. Semantic development uses
the documented business contract and development cases only and excludes holdout
tests even if the owner's environment variable is inherited.

After personal review, `python -m evals.validate_suite --suite holdout --freeze`
reruns reference checks and writes `evals/holdout_manifest.json`. That public file
contains only per-file SHA-256 digests, a combined suite hash, total and category/kind
counts, a schema version, database identity and freeze date. It includes no question,
SQL, note or per-case result. The command rejects any unreviewed case and refuses to
overwrite an existing commitment. The manifest must be committed **before semantic
implementation begins**. At the time this mechanism is implemented, personal review
is pending and no real holdout manifest has been created.

`--verify` recomputes the commitment from the external data. Holdout evaluation verifies
it before and after model execution, records the manifest digest, and prints a verified
yes/no field in the report. A mismatch stops evaluation rather than grading changed
data against a stale commitment. The explicit report field also makes unverified
synthetic/report-only artifacts distinguishable.

After the final evaluation, publish the committed case files and independent calculator
as an **exact-byte archive**, together with the results. Anyone can recompute the file
hashes and combined hash against the earlier committed manifest. Do not let line-ending
normalisation change the published bytes. Corrections require a new version and all
compared modes to be rerun; they must not silently overwrite the original commitment.

**Limitations.** The benchmark author inspected the holdout for correctness and is not
blind to it; the semantic implementation must derive its rules only from the shared
business contract and development cases in a separate session. The owner's personal
approval is still required. Moving a folder outside a repository reduces accidental
exposure but does not block arbitrary reads by another process using the same OS account.
A filesystem sandbox that excludes the directory, or a separately restricted account,
is needed for an OS-enforced boundary; this change does not claim to establish one.
A locally generated timestamp is not an independently witnessed timestamp; the earlier
committed hash provides the content commitment and the recorded development sequence.


## Decision 10: pre-review question quality amendment

Before any semantic implementation or holdout model evaluation, remove calculation
hints from natural-language questions without extending the business contract.
Development retains 50 cases: 40 data, 5 clarification, 4 security and 1 out-of-scope;
15 data cases explicitly test a documented default. Eight development cases have
question wording corrections. Every case now has a specific reference rationale.

The external suite retains 50 cases. Quality review changes 21 questions and converts
two data cases into clarification cases because the contract does not define their
requested measures. Its composition is now 38 data, 7 clarification, 4 security and
1 out-of-scope, with 27 default-assumption cases. These counts supersede the initial
40-data/5-clarification allocation; the success threshold and paired case-bootstrap
procedure remain unchanged. The primary denominator is 38 independent holdout cases,
with languages and repetitions clustered within each case. All 78 remaining data
references must agree with independent dataframe calculations before owner review.
Run artifacts record their actual data-case count; confirmatory analysis rejects
incomplete coverage. All personal approvals remain pending.


## Decision 11: development suite audit and ranking tie guard

An independent audit of the 50 development cases found 0 blockers, 5 major issues
(006, 009, 017, 019, 038), 20 minor ones and 25 cases without findings. Every
expected result matched its reference. A methodological limit remains: the auditor
saw the oracle files before finishing the later cases, so the audit is not fully blind.
It is not a personal approval; all `reviewed*` fields stay untouched.

**Ranking ties.** The current data has no tie at any ranking cutoff, but nothing
guaranteed that. The verification now fails when the N-th and (N+1)-th ranked values
of an `ORDER BY ... LIMIT N` reference are equal within tolerance (see
`docs/evaluation.md`). Rejected alternative: adding tie rules to the question texts.
That changes what is asked, may invent a business rule (for example the country-code
tie-break in 038) and does not protect later changes. The guard detects the problem
without altering the questions.

**Other changes.** The 009 English question now asks for English category names, like
the Hungarian one. Growth cases 037, 041 and 042 handle a zero or missing base: `NULLIF`
(and `NULLS LAST` in 041) in the SQL and an explicit `None` branch in the oracle.

**Deliberately unchanged.** The `default_assumption` tags remain inconsistently applied
across older and newer cases. The 15 tagged cases are a registered composition; changing
it requires a new suite version, not a silent relabelling.


## Decision 12: semantic layer as four traceable YAML files

**Context.** The semantic layer must beat the commented baseline by definitions, not by
being a second copy of the golden set. It is therefore written from the shared business
contract and the design decisions only, never from sealed cases.

**Decision.** `semantic/` holds `metrics.yaml`, `rules.yaml`, `joins.yaml` and
`examples.yaml`. Each file has a `version` (increased with every iteration) and every
metric, rule, join and example has a mandatory `source`: `contract:<section>` or
`decision:<number>`. A test checks that the section or decision exists. A rule that is in
neither document is not added. The eval report header prints the version and SHA-256 of
each file. The semantic prompt (`sql_semantic_v1`) is the commented prompt plus the rendered
layer, so semantic minus commented measures the layer and nothing else. The five examples
are written from the contract and a test rejects overlap with the development suite.
Nothing writes to `data/retail.duckdb`: no view, no table; the layer only describes SQL.

**Alternatives considered.** A metric-to-SQL compiler (dbt/MetricFlow style): too large for
the time budget and harder to explain. One `rules` list inside `metrics.yaml`: rules such as
the fiscal calendar or refusal behaviour are not measures, so they got their own file.

**Consequences.** Gaps in the contract stay gaps. Known gap: the meaning of relative
periods other than year-to-date ("last month", "last week") is not defined in the contract
and is therefore not in the layer (see decision 14). The `store`, `product` and `date` joins
are properties of the data model, not business rules, so they use a third source type,
`schema:<table>.<column>`, naming their key column; a test checks that the column exists.
YAML 1.1 reads a bare `on` key as boolean
true, so the join condition field is called `condition`.


## Decision 13: the scoring hash covers grading logic only

**Context.** Two runs may be compared (improved/regressed lists, paired analysis) only if
the same logic graded them. The run info recorded a scoring hash computed from the whole
`run_eval.py` file plus `compare.py`. Adding a command-line option therefore invalidated
every earlier run, although no answer would have been graded differently.

**Decision.** `scoring_hash()` fingerprints the syntax trees (not the text) of `grade`,
`assumptions_match`, `grade_primary` and the whole of `compare.py` (table matching and
tolerances). Comments, whitespace and line endings do not change it; any change of logic
does. The output schema keeps its own hash (`schema_hash`), which is also compared.
Tests show that changing a grading function or the tolerance changes the hash and that
replacing `main` or `run_evaluation` does not.

**Alternatives considered.** Hashing the whole file: safer against forgotten dependencies,
but unrelated edits break comparisons. Including `run_evaluation`: it only passes values
to the grading functions, and the runner tests cover it, so wiring edits stay free.

**Consequences.** Runs made before this change have a hash of the old kind and are not
comparable with new runs (they were rerun for that reason). A change in `run_evaluation`
that altered how results are assembled would not be seen by the hash; review such a change
by hand. A docstring edit inside a scoring function counts as a change (safe side).


## Decision 14: contract amendment for relative periods (2026-10-04)

**Context.** The contract defined only year-to-date. "Last month", "last quarter" and
similar phrases had no documented meaning, so a model could only guess, and the semantic
layer could not state a rule without inventing one.

**Decision.** The contract's time section now says that a relative period is the previous
complete period of the named calendar (last month = previous full calendar month, last
quarter = previous full calendar quarter, last year, last week = Monday-Sunday, yesterday),
that "this month/quarter/year" and "so far" mean period-to-date, and that the word "fiscal"
selects the fiscal counterparts. The rule `relative_periods` in `rules.yaml` (version 2)
repeats it with its source.

**Basis and timing.** The amendment follows ordinary business convention and development
experience: the development reference of case 002 ("last month", fixed evaluation date
2026-10-04) already uses 2026-09-01 to 2026-09-30, which matches; cases 018 and 036
(year-to-date, fiscal year so far) match the period-to-date rule; cases 022 and 049 expect a
clarification for other reasons (no measure named, no margin data) and are unaffected. It is
made before any holdout run and without knowledge of any holdout result. The contract is
in neither `frozen.json` nor `holdout_manifest.json`, so no commitment changes. The
holdout author already saw the sealed cases, so the amendment is not blind to them.

**Alternatives considered.** Leaving the gap: the model guesses, and the semantic layer
would not be evidence for the contract. Rolling windows ("last 30 days"): a different and
less common reading of "last month".

**Consequences.** Development results measured after this amendment are dev-informed,
like the rest of the layer. Weeks follow Monday-Sunday, not the fiscal week blocks.
