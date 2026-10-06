# Model comparison (diagnostic, dev-informed)

Development suite, semantic mode (v3), validator on, user carla, retry off, 3 repetitions,
300 questions per run. The two runs differ in the model; thinking is off in both (`claude_small`
sends no thinking field, `claude_mid` sends `between_tools`, the API's "off" value for this model;
see Decision 18).

| | claude_small (Haiku 4.5) | claude_mid (Sonnet 5.5) |
|---|---|---|
| Run file | `../2026-10-05-backend-validated/20261005-214754-012689_semantic_claude_small_validated.json` | `20261006-195312-146163_semantic_claude_mid_validated.json` |
| Primary accuracy | 89.6% (215/240); repetitions 73 / 72 / 70 of 80 | **97.5% (234/240)**; repetitions 78 / 78 / 78 of 80 |
| Strict / lenient (all 300) | 82% (246) / 92% (276) | 88% (264) / 96% (288) |
| Latency p50 / p95 | 4,576 ms / 7,336 ms | 4,920 ms / 8,265 ms |
| Cost per question | $0.00281 | $0.00784 |
| Cost of the run | $0.844 | $2.351 |
| Clarification rate (all 300 questions) | 9.0% (27); 0 on data questions | 8.0% (24); 0 on data questions |
| Invalid output | 2 | 0 |
| Security cases passed | 100% | 100% |

Notes:
- The cost columns are not exactly like for like: the claude_small run was priced before cache
  writes got their own price (Decision 18), so its cost is slightly low (realistically < $0.02).
- No paired analysis: `paired_analysis` requires identical `model` and `config_hash`, and the
  code was not loosened. The two reports side by side are the comparison.
- **The model comparison is diagnostic and dev-informed (the semantic layer was tuned on this
  development suite), not confirmatory.** Sonnet's three repetitions are identical (78/78/78),
  so the repetition spread says nothing about its run-to-run noise.
