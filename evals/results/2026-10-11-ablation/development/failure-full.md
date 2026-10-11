# Failure analysis: `semantic` mode

> **Heuristic.** The rule categories are heuristic text patterns on the model SQL versus the reference SQL, not proven causes. One failed answer can break several rules, so the counts add up to more than the number of failed answers.

- Run file: `20261010-140509-865763_semantic_claude_small.json`
- Scope: data questions only: 240 questions (40 cases, 3 repetitions, 2 languages)
- Failed the primary score: 21 questions in 6 of 40 cases

| rule label | failed questions | cases |
|---|---|---|
| other_unclassified | 15 | 4 |
| invalid_output | 3 | 1 |
| net_formula_no_vat | 3 | 1 |
| fx_missing | 3 | 1 |
