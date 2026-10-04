# Failure analysis: `commented` mode

> **Heuristic.** The rule categories are heuristic text patterns on the model SQL versus the reference SQL, not proven causes. One failed answer can break several rules, so the counts add up to more than the number of failed answers.

- Run file: `20261004-230326-929516_commented_claude_small.json`
- Scope: data questions only: 240 questions (40 cases, 3 repetitions, 2 languages)
- Failed the primary score: 204 questions in 36 of 40 cases

| rule label | failed questions | cases |
|---|---|---|
| test_store_not_excluded | 140 | 31 |
| net_formula_no_vat | 128 | 28 |
| returns_wrongly_excluded | 115 | 22 |
| fiscal_instead_of_calendar | 107 | 27 |
| fx_missing | 38 | 7 |
| returns_not_excluded | 34 | 7 |
| sql_error | 16 | 8 |
| basket_average_of_averages | 12 | 4 |
| clarification | 6 | 3 |
| refused | 3 | 2 |
| other_unclassified | 1 | 1 |
