# Failure analysis: `semantic` mode

> **Heuristic.** The rule categories are heuristic text patterns on the model SQL versus the reference SQL, not proven causes. One failed answer can break several rules, so the counts add up to more than the number of failed answers.

- Run file: `20261010-145808-459568_semantic_claude_small_no_rules.json`
- Scope: data questions only: 240 questions (40 cases, 3 repetitions, 2 languages)
- Failed the primary score: 75 questions in 16 of 40 cases

| rule label | failed questions | cases |
|---|---|---|
| other_unclassified | 27 | 8 |
| net_formula_no_vat | 22 | 5 |
| fx_missing | 22 | 5 |
| fiscal_instead_of_calendar | 21 | 6 |
| returns_not_excluded | 14 | 3 |
| calendar_instead_of_fiscal | 3 | 1 |
| clarification | 3 | 2 |
