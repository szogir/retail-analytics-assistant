# Evaluation operation

## Current release state

The development and held-out suites each contain 50 bilingual cases: 40 data results,
five clarifications, four security refusals and one unrelated request. All reference
results have independent DataFrame calculations. Both suites are **candidates awaiting
human review**, not frozen benchmark releases. `reviewed: false` is deliberate.

The original `evals/baseline.json` and `evals/reports/latest.md` are historical 28-case
artifacts. New runs are stored separately inside each suite's `artifacts/` directory.

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

The owner performs the corresponding holdout verification/review/freezing in the sealed
evaluation session, substituting `--suite holdout`, and uses `pytest -m review` to check
both approvals. Detailed holdout output stays under `evals/holdout/`; do not paste it into
the semantic development session. `pytest -m 'holdout and not review'` checks the sealed
references explicitly. Ordinary tests, lint and type checking exclude sealed content.

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
