# Failure analysis: `semantic` mode

> **Heuristic.** The rule categories are heuristic text patterns on the model SQL versus the reference SQL, not proven causes. One failed answer can break several rules, so the counts add up to more than the number of failed answers.

- Run file: `20261010-152419-359612_semantic_claude_small_metrics_joins.json`
- Scope: data questions only: 240 questions (40 cases, 3 repetitions, 2 languages)
- Failed the primary score: 102 questions in 23 of 40 cases

| rule label | failed questions | cases |
|---|---|---|
| fiscal_instead_of_calendar | 68 | 19 |
| other_unclassified | 13 | 5 |
| net_formula_no_vat | 13 | 4 |
| fx_missing | 13 | 4 |
| sql_error | 9 | 4 |
| clarification | 3 | 1 |
| returns_not_excluded | 2 | 1 |
