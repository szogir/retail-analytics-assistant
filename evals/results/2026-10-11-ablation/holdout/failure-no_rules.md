# Failure analysis: `semantic` mode

> **Heuristic.** The rule categories are heuristic text patterns on the model SQL versus the reference SQL, not proven causes. One failed answer can break several rules, so the counts add up to more than the number of failed answers.

- Run file: `20261011-115019-845894_semantic_claude_small_no_rules.json`
- Scope: data questions only: 228 questions (38 cases, 3 repetitions, 2 languages)
- Failed the primary score: 74 questions in 18 of 38 cases

| rule label | failed questions | cases |
|---|---|---|
| fiscal_instead_of_calendar | 27 | 7 |
| net_formula_no_vat | 27 | 6 |
| fx_missing | 27 | 6 |
| other_unclassified | 18 | 6 |
| returns_not_excluded | 12 | 3 |
| sql_error | 8 | 3 |
