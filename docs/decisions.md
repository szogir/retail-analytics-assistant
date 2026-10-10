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

*Update (2026-10-07): that suite exists, see Decision 17 (`evals/security_suite/`, 25 cases).*

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

**Live measurement of the retry mechanism (2026-10-06, `commented`, `claude_small`, validator on,
user carla, retry on, 3 repetitions, 50 cases x 2 languages x 3 = 300 questions, cost 1.15 USD,
run dump `evals/golden_set/artifacts/20261006-190250-350523_commented_claude_small_validated_retry.json`,
not versioned).**

| | count |
|---|---|
| First attempts that ended in `sql_error` or `blocked` (= retries made) | 13 |
| Retries that ended in a result table (ran SQL) | 11 |
| Of those, correct on the primary metric | 2 (cases 006 en, 019 hu) |
| Retries that stayed `sql_error` | 2 (004 hu, 020 hu, repetition 3) |

The first-attempt split between `sql_error` and `blocked` is not visible in this run (only the
final status was recorded; the `first_status` field was added afterwards), but no final status was
`blocked`. Final statuses: 246 answered, 36 refused, 16
clarification, 2 sql_error. Reading: the retry turned 11 of 13 failing statements into
statements that run, but only 2 of those 11 are also correct; the rest are the missing business
rules of `commented` mode (the same cases recur: 002, 004, 020, 038 in Hungarian). This confirms
the stated limit: the retry fixes syntax and execution errors, not business logic. No accuracy
comparison and no paired analysis were made; the 18% primary accuracy of this run is the
`commented` level and says nothing about the retry.

## Decision 18: cache-write pricing and the thinking setting of the model comparison (2026-10-06)

**Cache-write cost.** Until now the adapter folded cache-creation tokens into `input_tokens`, so a
cache write was priced at the normal input price. The 5-minute cache write costs more (Sonnet 5.5
2.50, Haiku 4.5 1.25 USD per million tokens, checked on the official price list on 2026-10-06).
`Usage` now carries `cache_creation_input_tokens` separately, the profiles have
`cache_write_per_mtok`, and `cost_usd` prices it (tests added). **How much earlier reports
under-stated cost:** the creation tokens of earlier runs were not stored, so the exact amount is
not recoverable and the old run files are left unchanged. The error is 0.25 x input price per
cache-written token (Haiku 0.25 USD, Sonnet 0.50 USD per million). Only the semantic system prompt
(about 5,300 tokens plus about 800 tokens of output schema) is long enough to be cached on Haiku;
within a continuous run the cache is written about once per cold start and then read, so the
realistic under-statement is well below 0.02 USD per run. The worst case (every one of 300 calls
writing the cache) is about 0.45 USD per 300-question Haiku run; the observed totals (about 0.85
USD) show reads dominated. Cost figures in earlier reports are therefore slightly low, not
wrong in order of magnitude. Reports from today on are priced with the write price.

**Thinking.** `claude_small` sends no `thinking` field. For `claude_mid` (Sonnet 5.5) a live probe
on 2026-10-06 showed that `thinking: {type: disabled}` is rejected (HTTP 400) and the API says to
send `{type: between_tools}` to turn thinking off: the model then does not think before
responding, and only short updates between tool calls come back as thinking blocks. Our calls use
no tools, so `between_tools` means no thinking, matching `claude_small`. The adapter sends the
profile's `request_options` unchanged. The old comment in `config/models.yaml` ("switch thinking
off") now matches the value, and the report header prints the thinking setting. Editing
`models.yaml` changes `config_hash`, so runs made before and after this edit are not pairable
(they would not be across models anyway).

**Config hash on HEAD.** On HEAD the `config_hash` differs from the one recorded in Decision 15,
because `models.yaml` gained the cache-write prices and the new comments. The confirmatory
configuration is the `holdout-v1` git tag. The behaviour of `claude_small` did not change, only the
cost calculation; `claude_mid` already had `thinking: between_tools` at `holdout-v1` (only its
comment and prices changed).

**Was thinking really off? Not proven.** The `claude_mid` run file
(`evals/results/2026-10-06-model-comparison/20261006-195312-146163_semantic_claude_mid_validated.json`)
records the request setting (`thinking: between_tools`) but no thinking blocks and no per-call token
counts: the adapter keeps only the parsed output and the usage totals of each call, and the per-case
rows store the cost, not the output tokens, so thinking tokens cannot be separated from answer
tokens. What we have is the API's error message for `disabled` (it names `between_tools` as the way to
turn thinking off), applied to calls without tools (no thinking). It is therefore **not proven** from our own data that the two profiles ran under
identical conditions; the model comparison (Decision 20) stays diagnostic. A one-off live probe that
prints `usage.output_tokens` and the content block types would settle it.

**Probe result (2026-10-07).** Three live calls, profile `claude_mid`, semantic prompt, same request
as the eval (including `thinking: between_tools`), `max_tokens` 4096. The questions were
development-style questions close to cases 001, 004 and 006 (not holdout questions):

| question | content block types | thinking block | `usage.output_tokens` |
|---|---|---|---|
| net sales in euro by country, fiscal year 2025 | `text` | no | 559 |
| average basket in Hungary | `text` | no | 567 |
| weekday with the highest net sales | `text` | no | 529 |

3 probe calls had no thinking block; strong signal, not complete proof; the comparison stays
diagnostic. The output token counts (about 530-570) are the size of the structured JSON answer
itself, which points the same way, but one cannot subtract an unknown from them, so it is a hint,
not a proof. The probe script was a throwaway and is not in the repository.

## Decision 19: the answer text of the CLI is a template, not a model summary (2026-10-06)

`ask` prints the answer sentence, the result table and a "What was computed" panel
(`presentation.py`, `cli.py`). The sentence is built from a fixed template; there is no second
model call.

- **Why:** every figure on the screen must come from the result table. A template cannot state a
  number the table does not contain; a model-written summary can, and would need its own
  number-vs-table check plus an extra call (cost, latency, non-determinism). Numbers are only
  re-formatted (`format_value`: separators, two decimals), never recalculated.
- **What the template says:** one value -> `name: value` (the name is the metric's label only
  when exactly one `metrics_used` entry equals a `metrics.yaml` name, otherwise the column
  name); several rows -> row count and column names, the table is the answer; clarification,
  refusal, block and errors in plain words (a block names the validator rule). The period is not
  stated, because the model's assumptions are free text and not a verified fact; a date column,
  if any, is in the table.
- **Metric definitions:** the panel resolves only names that equal a `metrics.yaml` name exactly
  (no case folding, no synonym matching). Every other `metrics_used` entry is printed as text with
  the label "not an identifiable metric" (hu: "nem azonosítható metrika") and no definition.
- **Assumptions and the refusal reason** are the model's words and are labelled as such.
- **Rejected alternative:** an LLM summary with a test that every number comes from the table.
  It would read better but needs the extra call and a check that cannot prove the text is
  faithful beyond its digits.
- **`eval`** calls `evals.run_eval.main`; only the development and security suites are
  reachable from the CLI, the holdout and its folder option are not.

## Decision 20: model comparison, claude_small vs claude_mid (2026-10-06)

Diagnostic and dev-informed, not confirmatory. Development suite, semantic v3, validator on, user
carla, 3 repetitions, same thinking-off setting (Decision 18). Primary accuracy 89.6% (Haiku 4.5)
vs 97.5% (Sonnet 5.5); p50/p95 latency 4.6 / 7.3 s vs 4.9 / 8.3 s; cost per question $0.0028 vs
$0.0078 (about 2.8x; the whole run $0.84 vs $2.35); clarification rate 9.0% vs 8.0%; security 100%
in both. Details and caveats: `evals/results/2026-10-06-model-comparison/comparison.md`. No paired
analysis (the tool requires identical model and configuration; it was not loosened).

The `claude_mid` thinking-off condition is not proven from stored data (see Decision 18); the
`config_hash` on HEAD differs from Decision 15 for the reason given there.

## Decision 21: line-ending tolerant check of the frozen development files (2026-10-07)

**Problem.** The fresh-clone trial (2026-10-07) showed that `run_eval --suite development` fails in
a new clone with "Frozen YAML files have changed". `frozen.json` records the SHA-256 of the raw
bytes of the case files, `oracles.py`, `legacy_oracles.py` and `reference_tools.py`. Those hashes
were taken on a Windows checkout (CRLF), but git stores LF (`.gitattributes`: `eol=lf`), so no
clone can reproduce them although the content is identical (`case_hash` and the database hash
matched). Unit tests did not notice, because they build their own temporary files.

**Chosen solution (D).** `provenance.matches_recorded_hash` compares the raw bytes first. If that
fails, the file is brought to the canonical CRLF form (every CRLF to LF, then every LF to CRLF) and
hashed again. A match then is accepted, and `require_frozen` returns the names of such files; the
eval prints "verified with line-ending normalization". Any other difference still fails, including
a changed content byte in an LF file and a mixed-ending file that differs even in canonical form.
Tests: CRLF file passes in an LF checkout; one changed content byte fails; a mixed-ending file
that does not match in canonical form fails; the holdout verification is not tolerant.

**Holdout unchanged.** `verify_commitment` and `build_commitment` still compare raw bytes only; the
published holdout is kept byte-identical with `.gitattributes` (`-text`). Tolerance there would
let a changed sealed file pass.

**Frozen artefacts are byte-for-byte unchanged:** `frozen.json`, `candidate.json`, the case files,
the oracles, `holdout_manifest.json`. There is no re-freeze.

**Rejected alternatives.** (A) *Line-ending-independent hashing plus a re-freeze*: it would rewrite
a frozen artefact, and the shared `file_hash` also underlies the holdout commitment, which must not
move. (B) *`-text` on the golden set and committing CRLF bytes*: a repository with CRLF files on
every platform, and still fragile against any editor or autocrlf setting. (C) *Documentation only*:
the quickstart of a fresh clone would not work.

**Limit.** The tolerance is for CRLF/LF only. A file with other transformations (tabs, trailing
spaces, encoding) is rejected, which is intended.

## Decision 22: review fixes - honest panel, secure defaults, definitions, unusable-answer cost (2026-10-07)

An independent review found five weaknesses. What changed and why:

- **Panel.** The panel showed the metric definition next to the SQL, which suggested that the SQL
  implements the definition. Nothing guarantees that. The two parts are now labelled "Metric named
  by the model (catalogue definition, not the executed code)" and "SQL actually executed". A
  heuristic check (`semantic/metric_check.py`, sqlglot) lists the columns the named metric needs
  (from its expression and mandatory filters) and warns when the executed SQL does not reference
  one of them. When nothing is missing it says only "found no missing element ... compares column
  names only"; it never shows a tick. With no catalogue metric named the panel says "no catalogue
  metric named, no check". Limit: it compares column names, not logic. Rejected: proving that the
  SQL equals the definition (needs a canonical form for arbitrary SQL).
- **Secure by default.** `ask(validate=True)` is the default, and `user` has no default in
  `ask()` or in the CLI (`--user` is required). Without `users_path` the default call raises
  instead of running unprotected. The eval runner passes `validate` explicitly, so the earlier
  measurements are reproducible with `validate=False` / `--no-validator`.
- **Definitions.** On the validated path, `intent == "definition"` with exactly one `metrics_used`
  entry that equals a `metrics.yaml` name gives the new status `definition`: the answer is the
  catalogue's text, no SQL runs, and the model's own SQL is ignored. Any other case keeps the old
  behaviour. `SqlAnswer` is unchanged, so the `schema_hash` is unchanged. **Grading:** the frozen
  `grade` and `grade_primary` treat every status other than the expected one as a failure; a test
  checks that `definition` fails for every kind of case and that the security scoring gives it no
  credit. A data question answered with a definition used to be `invalid_output` (no SQL), now
  it is `definition`; both fail, so no score changes. `scoring_hash` stays `1056bb8f...`.
- **Cost of unusable answers.** An answer that is refused, truncated or does not fit the schema
  was billed but its tokens were dropped. `LLMOutputError` now carries `usage` and `latency_ms`,
  the pipeline prices them, and a failed retry call adds its tokens to the question's cost.
  The SDK's `messages.parse()` raises on invalid JSON without handing over the response, so the
  adapter now calls `messages.with_raw_response.create()` and validates the JSON with Pydantic
  itself. A first version read the response out of the SDK's traceback; it was replaced because
  it relied on SDK internals. **The request is unchanged:** `tests/test_anthropic_payload.py`
  sends the old `parse()` call and the adapter's call through a fake HTTP transport and compares
  the raw request bodies; they are byte-identical for both profiles (including the thinking
  option). Only the SDK's own telemetry headers (`x-stainless-helper`, `x-stainless-raw-response`)
  differ. One detail needed for byte equality: in the output format the key `schema` comes
  before `type`, as the SDK builds it. A side effect: a truncated answer is now reported as
  "output cut off at max_tokens" (it used to be "does not match", because the cut JSON is
  invalid); the status is `invalid_output` in both cases, so no score changes. Live check on
  2026-10-07: `max_tokens=40` gives the same usage as before (6,675 cache-creation and 40 output
  tokens, about 0.0086 USD) with the right message; `pytest -m live` passes for both profiles
  and a `claude_mid` question runs. Rejected: the traceback reading; and dropping the cost of
  unusable answers (about 2 of 300 questions in the recorded runs). Earlier run files are not
  rewritten; costs of runs from now on can be slightly higher where answers were unusable.
- **Naming.** The latency shown is the time of the model call only, so panel and report now say
  "model latency".

**Flaky test, fixed.** `test_permission_references_agree_with_the_backend_and_forbidden_ones_differ`
failed in 1 of 20 isolated runs (before the fix) and once in a full run. Cause (from the failure
output): the test compared floats with `==`, and the same query gave 19573.26846946602 on the
user's connection and 19573.268469465904 on the full database. DuckDB sums in parallel and the two
connections hold the rows in a different physical order, so the last digits differ. It was not
row order. The test now uses the project's own table comparator (`compare_tables`, relative
tolerance 1e-6, row order ignored unless the case says otherwise) for both assertions. After the
fix the test passed 20 of 20 isolated runs, and the full suite is green; a failure in 1 of 20 is not
proven away by 20 passes, so the evidence is the identified cause and the tolerance, not the count.

**Checking discipline.** Commit `c9d7912` was made while a test was failing, because the check was
piped through `tail` and the pipe hid the exit code. Checks now run with `set -o pipefail` or
without a pipe, and the exit code is read before committing.


## Decision 23: ablation of the semantic layer, preregistered before the runs (2026-10-10)

**Context.** Decision 16 showed that the semantic layer as a whole lifts primary accuracy from
11.8% (commented) to 86.0% on the holdout. It did not show which part does the work: the rules,
the metric definitions with their mandatory filters, the join paths or the verified examples.
This decision fixes the question, the variants and the analysis before any ablation run is made.

**Variants** (`--ablation`, semantic mode only; prompt template, schema text and section order
unchanged, an omitted section disappears with its heading):

| variant | rules | metrics | join paths | examples | prompt SHA-256 (first 8) |
|---|---|---|---|---|---|
| `full` (default) | yes | yes | yes | yes | `e3e91b83` (= Decision 15) |
| `no_examples` | yes | yes | yes | no | `b6805633` |
| `no_rules` | no | yes | yes | yes | `2ea75723` |
| `metrics_joins` | no | yes | yes | no | `b54e0df9` |

Metrics and join paths are kept in every variant: without them the mode is "commented", which is
already measured. A test pins the `full` prompt to the frozen SHA-256 `e3e91b83…` and the naive and
commented prompts to their recorded values, and the scoring hash stays `1056bb8f…`, so every earlier
run remains valid. Rejected: one prompt file per variant, because the surrounding template text
would then change together with the content, two differences at once.

**Runs.** Profile `claude_small` (`claude-haiku-4-5`) only, mode `semantic`, 3 repetitions, both
languages, validator off, no user override (the holdout-v1 configuration), all four variants on:
- the development suite (dev-informed: the layer was tuned on it, Decision 15);
- the published holdout v1 (`--holdout-dir evals/holdout_published`, given explicitly for every
  variant including `full`), as **regression data**, not
  confirmatory; output in `evals/runs/holdout-regression/`, never inside the published folder.
  The holdout runs are started by the owner (the development session may not run
  `--suite holdout`).

`full` is re-run as well: `config_hash` on HEAD (`7dae3d7a…`) differs from all earlier semantic runs
(`17c53d78…`, price-only change, Decision 18), and the paired analysis does not relax that key.

**Primary analysis.** Per variant and suite: primary accuracy on data questions (240 development,
228 holdout), with the three repetitions shown separately. Paired, case-clustered bootstrap of each
ablated variant minus `full` on the same suite (`evals.paired_analysis --diagnostic`, 10,000
samples, seed 42): 3 comparisons per suite, no multiplicity correction, reported as diagnostic
estimates with intervals, without a success-rule verdict. `paired_analysis` was extended for this
only: `--diagnostic` accepts two holdout runs when both are semantic, the ablation variant is the
only difference, and the holdout commitment is verified; every other identity key (including
`config_hash`) must still match, and the output is labelled "DIAGNOSTIC
(published holdout, regression data)". In any ablation comparison, on either suite, the backend
settings (validator, retry, user) must match as well: only one thing changes. The confirmatory
branch is unchanged.

**Failure analysis.** `evals.failure_analysis` per run (holdout runs only against
`evals/holdout_published`): which trap labels return, compared with `full` of the same suite. The
labels are heuristic (text patterns on SQL), so a change is reported as counts, sampled by hand
before it is called a cause.

**Secondary question, named in advance (phase-4 hypothesis).** Decision 16 found that
clarification did not generalise (90% development, 45.2% holdout) and suggested, unverified, that
explicit rules and defaults make the model overconfident. Per variant and suite, two rates (status
`clarification`, also printed in every run report). Decision 16's 45.2% is a strict pass, which
also needs a non-empty clarification message; the reproducibility row therefore shows the strict
clarification pass too, and the "asked back" rate is labelled as status only:
- asked back on clarification cases (development 30 questions / 5 cases, holdout 42 / 7);
- asked back needlessly on data cases (240 / 228 questions).

The hypothesis predicts a higher first rate for `no_rules` and `metrics_joins` than for `full`. It
is called "consistent with the hypothesis" only if the direction is the same on both suites; a
difference on one suite only, or in opposite directions, is "not supported". With 5 and 7 cases the
rates are descriptive (no bootstrap), and a rise in needless questions alongside would mean "asks
more", not "judges better".

**Reproducibility check.** The `full` holdout result on HEAD is shown next to the Decision 16 value
(86.0%) as one separate row. Different `config_hash`, so the two are only placed side by side, never
paired. The row compares two code states, not two noise draws of one: between the `holdout-v1` tag
and HEAD the validator-off path also changed (executor, the Decision 22 `definition` status, the
usage capture of unusable answers). After the run, the two `info` objects are compared key by key
and every difference is listed in that row.

**Known confounds, stated before the runs.**
- Each metric's "Always filter" line carries trap knowledge (cancelled receipts, test stores), so
  `no_rules` is not "no trap knowledge"; it removes the rules list only.
- In `no_rules` the examples still name the removed rules in "Rules and metrics shown".
- The template paragraph mentions rules and verified examples in every variant.
- Effects need not add up: removing rules and examples together can differ from the sum of the
  single removals.
- One model, synthetic data, 40 and 38 data cases; the development suite is dev-informed.

**Consequences.** The ablation result is diagnostic. Decision 16 remains the confirmatory result.
Nothing is tuned on these numbers; a change to the layer prompted by them needs new development
cases and a new unseen suite before any confirmatory claim.
