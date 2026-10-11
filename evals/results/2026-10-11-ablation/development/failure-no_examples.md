# Failure analysis: `semantic` mode

> **Heuristic.** The rule categories are heuristic text patterns on the model SQL versus the reference SQL, not proven causes. One failed answer can break several rules, so the counts add up to more than the number of failed answers.

- Run file: `20261010-143147-354729_semantic_claude_small_no_examples.json`
- Scope: data questions only: 240 questions (40 cases, 3 repetitions, 2 languages)
- Failed the primary score: 39 questions in 11 of 40 cases

| rule label | failed questions | cases |
|---|---|---|
| other_unclassified | 30 | 8 |
| sql_error | 6 | 2 |
| invalid_output | 3 | 1 |
