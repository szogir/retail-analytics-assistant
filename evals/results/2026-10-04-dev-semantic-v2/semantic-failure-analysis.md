# Failure analysis: `semantic` mode

> **Heuristic.** The rule categories are heuristic text patterns on the model SQL versus the reference SQL, not proven causes. One failed answer can break several rules, so the counts add up to more than the number of failed answers.

- Run file: `20261004-232722-786318_semantic_claude_small.json`
- Scope: data questions only: 240 questions (40 cases, 3 repetitions, 2 languages)
- Failed the primary score: 40 questions in 10 of 40 cases

| rule label | failed questions | cases |
|---|---|---|
| other_unclassified | 14 | 4 |
| returns_not_excluded | 6 | 1 |
| net_formula_no_vat | 5 | 2 |
| fx_missing | 5 | 2 |
| clarification | 5 | 2 |
| invalid_output | 4 | 1 |
| refused | 3 | 1 |
| sql_error | 3 | 1 |
