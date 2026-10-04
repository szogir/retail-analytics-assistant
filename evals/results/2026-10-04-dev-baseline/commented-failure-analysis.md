# Failure analysis: `commented` mode

> **Heuristic.** The rule categories are heuristic text patterns on the model SQL versus the reference SQL, not proven causes. One failed answer can break several rules, so the counts add up to more than the number of failed answers.

- Run file: `20261004-212942-104783_commented_claude_small.json`
- Scope: data questions only: 240 questions (40 cases, 3 repetitions, 2 languages)
- Failed the primary score: 204 questions in 36 of 40 cases

| rule label | failed questions | cases |
|---|---|---|
| test_store_not_excluded | 138 | 31 |
| net_formula_no_vat | 129 | 28 |
| returns_wrongly_excluded | 116 | 22 |
| fiscal_instead_of_calendar | 111 | 27 |
| fx_missing | 40 | 7 |
| returns_not_excluded | 31 | 7 |
| basket_average_of_averages | 14 | 4 |
| sql_error | 11 | 4 |
| clarification | 7 | 3 |
| refused | 6 | 2 |
