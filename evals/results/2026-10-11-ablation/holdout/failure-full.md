# Failure analysis: `semantic` mode

> **Heuristic.** The rule categories are heuristic text patterns on the model SQL versus the reference SQL, not proven causes. One failed answer can break several rules, so the counts add up to more than the number of failed answers.

- Run file: `20261010-133302-379625_semantic_claude_small.json`
- Scope: data questions only: 228 questions (38 cases, 3 repetitions, 2 languages)
- Failed the primary score: 36 questions in 10 of 38 cases

| rule label | failed questions | cases |
|---|---|---|
| net_formula_no_vat | 17 | 4 |
| fx_missing | 17 | 4 |
| sql_error | 11 | 5 |
| returns_not_excluded | 9 | 2 |
| fiscal_instead_of_calendar | 6 | 2 |
| other_unclassified | 5 | 2 |
