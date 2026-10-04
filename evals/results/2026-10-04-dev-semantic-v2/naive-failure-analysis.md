# Failure analysis: `naive` mode

> **Heuristic.** The rule categories are heuristic text patterns on the model SQL versus the reference SQL, not proven causes. One failed answer can break several rules, so the counts add up to more than the number of failed answers.

- Run file: `20261004-223758-482623_naive_claude_small.json`
- Scope: data questions only: 240 questions (40 cases, 3 repetitions, 2 languages)
- Failed the primary score: 197 questions in 33 of 40 cases

| rule label | failed questions | cases |
|---|---|---|
| test_store_not_excluded | 181 | 33 |
| fiscal_instead_of_calendar | 126 | 28 |
| net_formula_no_vat | 118 | 27 |
| returns_wrongly_excluded | 103 | 21 |
| fx_missing | 40 | 7 |
| returns_not_excluded | 32 | 7 |
| fx_direction | 23 | 10 |
| cancelled_not_excluded | 15 | 5 |
| sql_error | 13 | 6 |
| basket_average_of_averages | 11 | 3 |
| clarification | 3 | 2 |
