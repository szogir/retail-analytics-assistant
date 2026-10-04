# Failure analysis: `naive` mode

> **Heuristic.** The rule categories are heuristic text patterns on the model SQL versus the reference SQL, not proven causes. One failed answer can break several rules, so the counts add up to more than the number of failed answers.

- Run file: `20261004-210434-466976_naive_claude_small.json`
- Scope: data questions only: 240 questions (40 cases, 3 repetitions, 2 languages)
- Failed the primary score: 199 questions in 34 of 40 cases

| rule label | failed questions | cases |
|---|---|---|
| test_store_not_excluded | 181 | 32 |
| fiscal_instead_of_calendar | 125 | 26 |
| net_formula_no_vat | 117 | 26 |
| returns_wrongly_excluded | 109 | 21 |
| fx_missing | 41 | 8 |
| returns_not_excluded | 34 | 7 |
| fx_direction | 22 | 11 |
| cancelled_not_excluded | 16 | 4 |
| sql_error | 15 | 7 |
| basket_average_of_averages | 12 | 3 |
| clarification | 3 | 1 |
