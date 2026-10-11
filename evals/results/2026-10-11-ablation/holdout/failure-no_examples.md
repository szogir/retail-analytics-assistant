# Failure analysis: `semantic` mode

> **Heuristic.** The rule categories are heuristic text patterns on the model SQL versus the reference SQL, not proven causes. One failed answer can break several rules, so the counts add up to more than the number of failed answers.

- Run file: `20261010-141258-565787_semantic_claude_small_no_examples.json`
- Scope: data questions only: 228 questions (38 cases, 3 repetitions, 2 languages)
- Failed the primary score: 62 questions in 16 of 38 cases

| rule label | failed questions | cases |
|---|---|---|
| net_formula_no_vat | 31 | 9 |
| fx_missing | 31 | 9 |
| other_unclassified | 23 | 5 |
| returns_not_excluded | 11 | 3 |
| fiscal_instead_of_calendar | 4 | 2 |
| returns_wrongly_excluded | 3 | 1 |
| cancelled_not_excluded | 3 | 1 |
| sql_error | 3 | 3 |
