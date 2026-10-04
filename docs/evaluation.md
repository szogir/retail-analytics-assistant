# Evaluation operation

## Current release state

Both suites contain 50 bilingual cases. Development has 40 data results and five
clarifications; holdout has 38 data results and seven clarifications after the
pre-review quality amendment (Decision 10). Each has four security refusals and one
unrelated request. All 78 data reference
results have independent DataFrame calculations. Both suites are **candidates awaiting
human review**, not frozen benchmark releases. `reviewed: false` is deliberate.

The original `evals/baseline.json` and `evals/reports/latest.md` are historical 28-case
artifacts. New runs are stored separately inside each suite's `artifacts/` directory.
The holdout is physically outside the repository. Configure it only in the owner's
evaluation environment through `HOLDOUT_DIR` or the explicit `--holdout-dir` option;
there is no repository-local default. Missing or empty suites are errors.

## Offline verification and human review

```bash
uv run python -m evals.validate_suite --suite development
```

This checks every development reference, writes `evals/golden_set/candidate.json` and
creates `evals/golden_set/artifacts/review.md`. The worksheet includes both questions,
the reference SQL, its independently checked result, notes and assumption checks.
Review both question meanings and calculations; two agreeing programs can share a
conceptual error. After personally reviewing a case, the owner sets:

```yaml
reviewed: true
reviewed_on: 2026-10-04  # use the actual review date
reviewed_by: Richard
```

### Ranking tie guard

Reference SQL of the form `ORDER BY ... LIMIT N` picks an arbitrary row when the N-th and
(N+1)-th values are equal, and the question does not say how to break such a tie. The
verification therefore reruns every such query without `LIMIT` and **fails** if the first
sort key of rows N and N+1 is equal within the comparison tolerance (relative 1e-6).

- Cases are recognised from the SQL (top-level `ORDER BY` plus numeric `LIMIT`); no YAML
  field is needed, so the same code protects the sealed suite without editing its files.
  Currently this covers 006, 009, 017, 019, 038 and 041.
- The guard is stricter than necessary where the question states a tie rule (041): any
  tie in the first key is reported.
- Not covered: rankings built with window functions (047). Its question states the
  tie rule, so the stated rule decides.
- Question texts are not extended with tie rules; a tie would show up as a failed
  verification, to be handled by a deliberate versioned change.

Approval records are an audit trail and a release gate, not proof that a person really
read a file. Automated verification must never fabricate human approval.

```bash
uv run pytest -m 'review and not holdout'
uv run python -m evals.validate_suite --suite development --freeze
```

The review test **fails while any case is unreviewed**. It is an explicit release check,
excluded from ordinary implementation tests. Freezing reruns independent verification
and refuses to overwrite an existing `frozen.json`. Live evaluation requires reviewed
cases and matching case, file, oracle and database fingerprints.

The owner performs holdout verification/review/freezing in the sealed evaluation session,
substituting `--suite holdout`, and uses `pytest -m review` to check both approvals.
Detailed output stays under the external directory's `artifacts/`; do not paste it into
the semantic development session. `pytest -m 'holdout and not review'` checks the sealed
references locally when `HOLDOUT_DIR` is set; otherwise it skips with an explicit reason.
Pending personal-approval tests are xfail; the actual freeze command still rejects them.
Development sessions must use `pytest -m 'not live and not review and not holdout'` even
when they inherit the owner's environment. Lint/type checks do not discover external data.

The owner freezes and verifies the external suite with:

```bash
uv run python -m evals.validate_suite --suite holdout --freeze
uv run python -m evals.validate_suite --suite holdout --verify
```

The first command writes the content-free public commitment at
`evals/holdout_manifest.json`; the second recomputes it from the configured external
directory. The command refuses unreviewed data and an existing manifest. Do not run
freeze until personal review is complete. Commit the resulting manifest before
semantic implementation; after the final evaluation, publish the exact-byte case
archive so others can verify it. Holdout reports include this manifest's SHA-256 and
the verification state. The public schema rejects additional content-bearing fields.

## Measured runs after release

```bash
uv run python -m evals.run_eval --suite development --mode naive --profile claude_small --repetitions 3 --save-baseline
uv run python -m evals.run_eval --suite development --mode commented --profile claude_small --repetitions 3
```

The commented mode adds stored column metadata to the same answer instructions, without
metric definitions. Semantic mode remains unimplemented until the suites are approved
and frozen. After semantic development is complete and the implementation is fixed,
the owner runs all three modes on the holdout, each with `--repetitions 3 --lang both`.
The holdout runner rejects partial-case or single-language execution. It is not a tuning
loop; archive every full run, including failures.

To compare the resulting three-repetition JSON dumps:

```bash
uv run python -m evals.paired_analysis path/to/commented-run.json path/to/semantic-run.json
```

This requires matching suite/data/scoring/model identities and both languages in all
three repetitions. The primary confirmatory comparison is semantic minus commented;
semantic minus naive is secondary. The predeclared success rule is a gain of at least
10 percentage points with the 95% case-bootstrap interval entirely above zero.

## Limitations and boundaries

- A case hash identifies content; a local timestamp is not an independent timestamping
  service. Preserve the candidate/frozen manifests through normal version control when
  the owner explicitly authorizes a commit.
- The database fingerprint covers the exact file. Regenerating a logically equivalent
  database may change its binary hash; do not replace it mid-comparison. Revalidate and
  version the release if the recorded file is intentionally replaced.
- Assumption regex checks are an auditable lexical proxy. Numerical success, explanation
  success and security behaviour are reported separately. All explanations are retained.
- Read-deny settings are a guardrail, not an OS-level isolation guarantee. A separate
  development checkout without sealed data provides a stronger boundary.
- The benchmark's finite, manually selected cases do not establish population accuracy
  for arbitrary questions. Repetitions and translations are not independent cases.
