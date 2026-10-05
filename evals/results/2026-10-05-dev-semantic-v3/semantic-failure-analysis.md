# Failure analysis: `semantic` mode

> **Heuristic.** The rule categories are heuristic text patterns on the model SQL versus the reference SQL, not proven causes. One failed answer can break several rules, so the counts add up to more than the number of failed answers.

- Run file: `20261005-104027-310016_semantic_claude_small.json`
- Scope: data questions only: 240 questions (40 cases, 3 repetitions, 2 languages)
- Failed the primary score: 24 questions in 8 of 40 cases

| rule label | failed questions | cases |
|---|---|---|
| other_unclassified | 16 | 5 |
| net_formula_no_vat | 5 | 1 |
| fx_missing | 5 | 1 |
| invalid_output | 2 | 1 |
| returns_not_excluded | 2 | 1 |
| sql_error | 1 | 1 |
