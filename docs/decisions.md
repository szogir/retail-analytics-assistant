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


## Decision 15: pre-holdout freeze (2026-10-05)

**Context.** The semantic layer went through three development iterations (v1-v3). Every
iteration was informed by the development suite, so its results are dev-informed. The
held-out suite is the only confirmatory evidence, and it is only meaningful if nothing
changes after this point.

**Decision.** From this commit on there is no more tuning of the prompt, the semantic files,
the model configuration or the scoring. The frozen state is:

| item | SHA-256 |
|---|---|
| prompt `config/prompts/sql_semantic_v1.md` | `e3e91b83212118e600cd8b2bf8a754166eeb5c27ff574c8317c12acbbaa6cc25` |
| `semantic/metrics.yaml` (v1) | `b4eda0773a24567a88b200c3822d17d160ba012e935f97362e71c26d8b4dd566` |
| `semantic/rules.yaml` (v3) | `5b17a79351d2d18302ed1ede17eb8ceda7d7144cf1e39153e726ab64978fe5df` |
| `semantic/joins.yaml` (v1) | `7e98e881014ca71cf87b1989eaf280e7daaeffc0ed1236975acbc18a0042b472` |
| `semantic/examples.yaml` (v1) | `6c5b110f4cff8e44fe2a55265532d91688ffb74baa68b512c178b66e8ab1bd61` |
| model configuration `config/models.yaml` | `17c53d78e08cbd10769139e5f329ed66827358a749a054747cd4063fd0c34b46` |
| scoring (grading logic fingerprint, Decision 13) | `1056bb8f5c5fd44683dddbb78260560811c205ce3202117e20d70db4c8d69349` |
| database `data/retail.duckdb` | `741bd4c18d8f81433565e2cd96edfe5751283f914753583fdbb82a91188df965` |
| development case set | `c8a7d537145a97b1795e61f49cc097f03e5e92e4b01884bdc36d58e11f0849fd` |

Frozen code commit: `321a985` (rules v3). The commit that records this decision changes
documentation only.

Confirmatory configuration: the current pipeline, **self-correction retry off** (not
implemented yet), profile `claude_small`, mode `semantic`, 3 repetitions, one question per
case and language. The hashes above are the ones printed in the v3 run report
(`evals/results/2026-10-05-dev-semantic-v3/semantic-report.md`); the holdout report must
show the same values, otherwise the run is not comparable.

**Known limits, deliberately not fixed.** Cases 042 (LAG computed before the WHERE filter)
and 044 are model limits, not missing definitions: a rule or example for them would be
tuning to the case. They stay as known failures. Also unresolved, on the preregistered main
metric (primary on data cases, strict on the rest; case table in
`evals/results/2026-10-05-dev-semantic-v3/v2-vs-v3-cases.md`): 038 (2/6), 045 (3/6; the
Hungarian answer rounds to 2 decimals), 037 and 039 (4/6), 005 and 012 (5/6), and the
clarification case 022 (3/6). Cases 006, 017 and 019 are 6/6 on the main metric; they looked
unresolved only on the legacy strict metric, which is not the score of record. The contract
defines only one product group (milk); no other product group was added.

**Prompt file name.** The prompt file is still called `sql_semantic_v1.md`, but its content
changed in v3 (SHA-256 `e0457b…` → `e3e91b…`). The SHA-256 is authoritative, not the file
name.

**Alternatives considered.** Another iteration on the remaining failures: each further fix
makes the development score less informative about unseen questions. Freezing earlier (after
v2): the v3 changes are general rules traceable to the contract (a wrong "both labels"
reading, the cancellation base, master-data scope), so they were worth one more round.

**Consequences.** The holdout run is started by the owner in a separate window, not by the
development session. Its result is reported as measured, whatever it is, and is never used
to tune anything.


## Decision 16: confirmatory holdout result (2026-10-05)

**Run.** The owner ran naive, commented and semantic modes on the sealed holdout in a
separate session: profile `claude_small` (`claude-haiku-4-5`), 3 repetitions, both
languages, 300 questions per mode, 38 data cases (228 data questions), 7 clarification,
4 security and 1 out-of-scope case. Holdout manifest `91b689f8…` verified before and
after each run. Prompt, semantic files, model configuration, scoring and database hashes
match the Decision 15 freeze exactly. Total cost about 3.5 USD.

**Results.**

| | naive | commented | semantic |
|---|---|---|---|
| Primary accuracy (228 data questions) | 11.0% | 11.8% | **86.0%** |
| Per repetition | 10.5 / 10.5 / 11.8% | 11.8 / 11.8 / 11.8% | 84.2 / 86.8 / 86.8% |
| Clarification cases (42 questions) | 31.0% | 14.3% | 45.2% |
| Security cases (24 questions) | 87.5% | 75.0% | 100% |
| Strict, all questions (legacy) | 21.7% | 19.0% | 74.7% |
| Lenient, all questions (legacy) | 31.3% | 29.7% | 84.0% |

**Confirmatory comparison.** Semantic minus commented: **+74.1 pp**, 95% case-bootstrap
interval +61.0 to +85.1 pp (38 cases, 10,000 samples, seed 42). The preregistered success
rule (at least +10 pp, lower bound above zero) is met. Secondary: semantic minus naive
+75.0 pp (+63.2 to +85.5).

**Interpretation.**
- Data accuracy generalised: 90.0% on the development suite (dev-informed) versus 86.0%
  on the unseen holdout. The 4 pp gap is the expected optimism of tuning on development data.
- Column comments alone do not help (11.0% vs 11.8%); the gain comes from business rules.
- Clarification did NOT generalise: 90% on development, 45.2% on holdout. The semantic
  layer is still better than both baselines, but it often answers with assumptions where
  it should ask. Probable cause (unverified): explicit defaults make the model
  overconfident. This is not tuned on holdout; any fix needs new development cases and a
  new unseen suite for a confirmatory claim.
- Security: only the semantic mode passed every security case in every repetition, so the
  tested refusal behaviour is claimed for that mode only. Naive and commented failed 3 and
  6 of 24. Refusal behaviour is prompt-based, not enforcement; backend validation and
  per-user views (day 5) are the actual control.

**Limits.** Synthetic data; the contract, data and cases were written by the same project;
one model; 38 data cases; the bootstrap assumes case exchangeability and does not
guarantee accuracy on arbitrary real-world questions.

**Consequences.** The holdout is now spent: from here it is regression data only. Its
exact-byte case archive is published with the final README so the commitment can be
verified. Pipeline changes (validator, permissions, self-correction) are measured on the
development and security suites and do not inherit this confirmatory result.


## Decision 17: backend security architecture (2026-10-05)

**Context.** Decision 16 showed that refusal in the prompt is not a control: the naive and
commented modes failed 3 and 6 of 24 security questions on the holdout. The control has to
hold even when the model writes bad SQL.

**Decision.** Two independent backend layers sit between the model and the data, and neither
depends on the prompt:

1. **Validator** (`sql/validator.py`, sqlglot, DuckDB dialect). Exactly one statement; the root
   must be a SELECT or a set operation (WITH is part of a SELECT); every table must be on the
   allow-list (six tables) or a CTE of the statement itself; no schema or catalog qualification
   (so no `raw`); table functions only from an allow-list (`range`, `generate_series`,
   `unnest`); scalar functions are checked against a deny-list and name families (`query`,
   `query_table`, `getvariable`, `current_setting`, `getenv`, `glob`, `read_*`, `sniff_*`,
   `duckdb_*`, `pragma_*`, `*_scan`). Unparsable SQL is refused (fail closed) but reported as
   `sql_error`, not `blocked`. Every violation is reported as rule name + token.
2. **Per-user connection** (`sql/access.py`, `config/users.yaml`). A new in-memory connection
   per question: `raw` attached READ_ONLY, the user's stores selected, the filtered data
   COPIED into temp tables with the original names, then `DETACH raw`, `enable_external_access
   = false`, a memory limit and `lock_configuration = true`.

**Why copies and DETACH instead of filtered views over an attached `raw`.** With views the
hidden database stays attached and `raw.main.fact_sales` is reachable by name inside the
connection, so only the validator would protect it. We measured the strict variant: setup takes
about 0.1-0.2 s per user on the full database (1.45 M rows), under the 2 s limit set in
advance, so it is the solution. Tests prove that `raw` is no longer in `duckdb_databases()`,
that `raw.*` queries fail, and that the settings cannot be changed or re-enabled afterwards
(on the installed DuckDB 1.5.6). The database file hash is unchanged after setup and use.

**Row limit.** Not enforced by rewriting the query. Wrapping in `SELECT * FROM (...) LIMIT n`
can lose an inner ORDER BY and does not fit WITH/UNION; the executor's `fetchmany(limit + 1)`
caps the result and reports truncation without touching the SQL.

**What it protects.** Writes and DDL (not SELECT, and the file is opened read-only anyway);
file and system access (validator and `enable_external_access = false`); reading the `raw`
schema (validator, and the schema no longer exists in the connection); reading other regions'
rows (the connection only holds the user's stores, whatever SQL runs); runaway queries (memory
limit and the executor timeout). The permission filter scopes rows only; the test-store and
cancellation rules stay business logic in the SQL.

**What it does NOT protect.**
- **Prompt extraction.** The validator checks SQL, not prose. A model that repeats its
  instructions in `approach` or `assumptions` is not stopped. The suite detects it with
  verbatim sentences of the prompt (documented in `docs/evaluation.md`); the prompt itself
  contains no secret and is public in the repository.
- **Column-level or measure-level rules.** The only access rule is the store filter; there
  are no per-column or per-metric permissions.
- **Correctness.** A wrong but allowed query still returns a wrong number; that is measured by
  accuracy, not by security.
- **Denial of service beyond the limits** (a slow but allowed query is cut by the timeout, not
  prevented), and anything outside this process (the host, the API key, `users.yaml` itself).
- The validator's deny-list for scalar functions is a list: a new DuckDB function that reaches
  the outside would need adding. The second layer (no external access, no `raw`) is why that
  gap is not a leak.

**Measurement state.** The offline tests cover the layers and a fake model that obeys every
attack. Live numbers (model refused / backend blocked / leaked per mode, and the accuracy
regression with the validator on) are recorded after the live runs in a later entry. The
holdout label `holdout-v1` and Decision 16 are untouched: the new configuration runs only on
the development and security suites and does not inherit the +74 pp result.

**Alternatives considered.** Filtered views over an attached `raw` (cheaper setup, but `raw` is
reachable by name, so only the validator would stand between the model and the hidden data).
A prompt-only rule (rejected by Decision 16). A regex validator or `sqlparse` (cannot tell a
table from a string literal or a comment).

**Security suite identity (recorded before the live run).** `evals/security_suite/` (25 cases),
case SHA-256 `82f9d05ea4eaca862314a9be13dff3082c7c65eb44424429400f85fe2a729a3f`, added in
commit `40923b5`; the scoring and the report code that will run it are at `dc4d3da`. This
suite is a self-written capability and regression test, authored in the same working session as
the validator and the access layer it tests; it is not an independent measurement, and a pass
shows that the implemented layers behave as the author intended, not that no other attack
exists.

**Live measurement (2026-10-05, profile `claude_small`, code `dc4d3da`, files in
`evals/results/2026-10-05-backend-validated/`).** Diagnostic runs; they do not touch the
holdout result of Decision 16. Total cost about 1.87 USD.

Security suite (25 cases x 2 languages x 3 repetitions = 150 questions per mode, validator on,
each case run as its own user: anna/carla):

| mode | model refused | backend blocked | leaked | scoped correct | scoped wrong | passed |
|---|---|---|---|---|---|---|
| naive | 96 | 0 | 0 | 18 | 36 | 76% |
| commented | 96 | 0 | 0 | 18 | 35 (+1 SQL error) | 76% |
| semantic | 96 | 0 | 0 | 54 | 0 | 100% |

Every repetition gave the same split (32 refusals per repetition in each mode).

- **leaked = 0 in all three modes and all nine repetitions.**
- **The backend block never fired live**: the model refused all 16 attack cases in every mode,
  so `backend blocked` is 0. The live run therefore shows no case in which the validator was the
  deciding layer; that behaviour is evidenced only by the offline tests (including a fake model
  that obeys every attack: 16/16 blocked, 0 leaked). The naive and commented failures of the
  holdout (Decision 16) were not reproduced with these case wordings, so these runs neither
  confirm nor refute the value of the backend against a model that does comply.
- The `scoped wrong` results of naive and commented are accuracy errors, not permission errors:
  they occur in p01, p02, p03, p04 (anna) and in the carla controls p08 and p09, and come from
  the missing business rules (for example VAT not subtracted, fiscal instead of calendar
  month). No `scope_other` case (p05, p06) and no whole-chain total leaked, and anna never
  received a value equal to the unscoped reference.

Development suite, semantic mode, validator on, user carla, 3 repetitions, 300 questions:

| | v3 (no backend layers) | with validator and user connection |
|---|---|---|
| Primary accuracy | 90.0% (216/240) | **89.6% (215/240)** |
| Strict / lenient | 83% / 92% | 82% / 92% |
| Questions blocked by the validator | n/a | **0** (no rule fired) |
| Cost | 0.85 USD | 0.84 USD |

Paired diagnostic (`paired_analysis --diagnostic`, 40 cases, 10,000 samples, seed 42):
-0.4 pp, 95% interval -2.9 to +2.1 pp. The differences (5 questions improved, 6 regressed on
the primary metric, spread over cases 005, 012, 037, 038, 039, 044, 046) are the run-to-run
noise already seen between earlier identical runs; no regression is attributable to the
validator, which blocked nothing. The aim was that the backend does not reduce accuracy; this
is consistent with that, within the resolution of the test (about +-3 pp).

### Real-model evidence (holdout, owner-run)

The owner ran the new validator offline over the recorded holdout runs (Decision 16, no new
model calls). Of the security failures, naive had 3 (all answered with SQL) and commented had 6
(3 clarifications instead of refusal, 3 answered with SQL). All 6 SQL statements pass the
validator: they read only allow-listed tables and attempt no write, file, system or raw access.
These failures were behavioural (answering or clarifying where a refusal was expected), not
executed attacks, so the backend would not have changed them. Across all live runs (development,
holdout, security suite) the model never produced an unsafe statement; the backend's blocking is
demonstrated only by offline adversarial tests with a fully compliant fake model. The backend is
defence in depth against a threat not observed live in this evaluation. Decision 16's sentence
that backend validation is "the actual control" is narrowed accordingly: it controls unsafe SQL
and cross-region data access; it does not fix wrong refusal behaviour.

### Self-correction retry (2026-10-06)

`ask(..., retry=True)` / `--retry` (default off, development suite only). After a `sql_error` or
`blocked` result the model is called exactly once more with its failed SQL and the error text (no
data rows). The retried SQL takes the same path as the first one (validator, the user's filtered
connection, executor), so a retry is not a way around any backend layer. Clarifications,
refusals and invalid output are never retried. Cost and latency of both calls are added up; the
report states how many retries were made and how many ended in a result table. The alternative,
several retries, was rejected: it hides how often the first answer was wrong and leaves cost
unbounded.

Offline tests (fake model): wrong first SQL, correct second -> answered; second SQL also
forbidden -> blocked, no result returned (leaked 0), exactly two model calls.

**The security suite is not re-run with retry.** In the live security runs the validator never
blocked anything (`backend blocked` = 0 in all modes and repetitions), so a retry after a block
had nothing to act on; a live run would measure nothing the offline tests do not show. The CLI
refuses `--retry` on the security suite and on the holdout.

**What the retry can and cannot do.** It corrects syntax and execution errors (a wrong column
name, an unparsable statement) and validator blocks; it does not correct business logic, because
a wrong-but-running statement is never retried. In semantic mode there was nothing for it to
correct live: the validated development run (3 repetitions, 300 questions) had 0 `sql_error` and
0 `blocked` results, so a semantic retry run would measure nothing. The live measurement of the
mechanism therefore uses `commented` mode (`--retry`, validator on, user carla, 3 repetitions):
it reports how many first attempts ended in `sql_error` or `blocked`, how many retries ran, how
many of those ended in a result, and how many of those are correct on the primary metric. It is
not an accuracy comparison and has no paired analysis.
