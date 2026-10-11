# Failure analysis: `semantic` mode

> **Heuristic.** The rule categories are heuristic text patterns on the model SQL versus the reference SQL, not proven causes. One failed answer can break several rules, so the counts add up to more than the number of failed answers.

- Run file: `20261011-122155-404544_semantic_claude_small_metrics_joins.json`
- Scope: data questions only: 228 questions (38 cases, 3 repetitions, 2 languages)
- Failed the primary score: 122 questions in 26 of 38 cases

| rule label | failed questions | cases |
|---|---|---|
| fiscal_instead_of_calendar | 84 | 20 |
| net_formula_no_vat | 36 | 8 |
| fx_missing | 36 | 8 |
| other_unclassified | 18 | 5 |
| returns_not_excluded | 15 | 3 |
| sql_error | 2 | 1 |
