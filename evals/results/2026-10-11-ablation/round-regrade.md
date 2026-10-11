# Diagnostic re-grade: answers that failed only because of ROUND()

> **Diagnostic, not a score.** The primary scores in `summary.md` stay as graded
> (`scoring_hash` 1056bb8f…, strict relative tolerance 1e-6 in `evals/compare.py`). This
> re-grade was made after the runs, offline, to check a pattern seen by hand; it is not a
> scoring change and nothing was tuned on it.

**Why.** Hand sampling of the `no_examples` failures (development 007, 008, 015, 033, 038)
showed SQL with the right logic wrapped in `ROUND(x, 2)` or `ROUND(x, 4)`. The primary score
compares numbers with a relative tolerance of 1e-6, so a ratio such as 0.0412 rounded to four
decimals fails. The verified examples show unrounded SQL; without them the model starts to
round.

**Method.** For every data question that failed the primary score, was `answered`, and whose
SQL contains `ROUND(`: parse the SQL with sqlglot (DuckDB dialect), replace every `ROUND(x, k)`
node with `x`, run it read-only on `data/retail.duckdb`, and compare with the reference using
the same `compare_tables(...).primary` as the scoring. Nothing else in the SQL is changed.

| suite | variant | failed with ROUND | pass without ROUND | still fail (cases) | primary as scored | primary if those passed |
|---|---|---|---|---|---|---|
| development | full | 3 | 3 (045) | - | 91.2% (219/240) | 92.5% (222/240) |
| development | no_examples | 23 | 17 (007, 008, 015, 033, 045) | 038, 042 | 83.8% (201/240) | 90.8% (218/240) |
| development | no_rules | 6 | 3 (045) | 007 | 68.8% (165/240) | 70.0% (168/240) |
| development | metrics_joins | 16 | 3 (045) | 015, 020, 038, 045 | 57.5% (138/240) | 58.8% (141/240) |
| holdout | full | 1 | 1 (123) | - | 84.2% (192/228) | 84.6% (193/228) |
| holdout | no_examples | 27 | 16 (102, 110, 118, 123, 128, 135) | 105, 110, 123 | 72.8% (166/228) | 79.8% (182/228) |
| holdout | no_rules | 6 | 3 (123) | 110 | 67.5% (154/228) | 68.9% (157/228) |
| holdout | metrics_joins | 18 | 6 (110, 135) | 102, 105, 110, 123 | 46.5% (106/228) | 49.1% (112/228) |

**Reading.** Compared on equal terms (both `full` and the variant re-graded), the
`no_examples` gap to `full` narrows from 18 to 4 questions on development (92.5% versus 90.8%)
and from 26 to 11 questions on the holdout (84.6% versus 79.8%, about -4.8 pp). On development
the examples' effect is almost all rounding; on the holdout a little over half of it. Removing
the rules is not a rounding effect: `no_rules` and `metrics_joins` change by 1-3 points only.

Script (run from the repository root with `PYTHONPATH=.`):

```python
import glob, json
from pathlib import Path
import sqlglot
from sqlglot import exp
from evals.compare import compare_tables
from evals.golden import load_golden_set
from retail_assistant.sql.executor import execute_query

DB = Path("data/retail.duckdb")
for suite, folder in (("development", "evals/golden_set"), ("holdout", "evals/holdout_published")):
    cases = {c.id: c for c in load_golden_set(Path(folder))}
    for path in sorted(glob.glob(f"evals/results/2026-10-11-ablation/{suite}/2026*.json")):
        run = json.load(open(path, encoding="utf-8"))
        passed = 0
        for r in run["results"]:
            if r["expected_kind"] not in ("result", "result_scoped") or r["primary"]:
                continue
            if r["status"] != "answered" or "round(" not in r["sql"].lower():
                continue
            case = cases[r["case_id"]]
            tree = sqlglot.parse_one(r["sql"], read="duckdb")
            tree = tree.transform(lambda n: n.this if isinstance(n, exp.Round) else n)
            result = execute_query(DB, tree.sql(dialect="duckdb"))
            reference = execute_query(DB, case.reference_sql)
            passed += compare_tables(reference.rows, result.rows, case.order_sensitive).primary
        print(suite, run["info"]["ablation"], passed)
```
