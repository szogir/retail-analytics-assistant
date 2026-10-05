# Evaluation report

- Run date: 2026-10-05
- Mode: `semantic`, profile: `claude_small`, model: `claude-haiku-4-5`
- Prompt version: `sql_semantic_v1`, output token limit: 4096
- Prices checked on: 2026-10-04
- Golden cases: 50, questions asked: 300 (every case in each language)
- Suite: development; repetitions: 3; scoring: execution_v2
- Case SHA-256: `c8a7d537145a97b1795e61f49cc097f03e5e92e4b01884bdc36d58e11f0849fd`
- Database SHA-256: `741bd4c18d8f81433565e2cd96edfe5751283f914753583fdbb82a91188df965`
- Prompt SHA-256: `e3e91b83212118e600cd8b2bf8a754166eeb5c27ff574c8317c12acbbaa6cc25`
- Model configuration SHA-256: `17c53d78e08cbd10769139e5f329ed66827358a749a054747cd4063fd0c34b46`
- Scoring SHA-256: `1056bb8f5c5fd44683dddbb78260560811c205ce3202117e20d70db4c8d69349`; output schema SHA-256: `78eae2676e93a7cf799d5b5dabbdc6b6e05cf32b1e1201e77eaaf2ce10ecf5ed`
- Semantic file `examples.yaml` v1 SHA-256: `6c5b110f4cff8e44fe2a55265532d91688ffb74baa68b512c178b66e8ab1bd61`
- Semantic file `joins.yaml` v1 SHA-256: `7e98e881014ca71cf87b1989eaf280e7daaeffc0ed1236975acbc18a0042b472`
- Semantic file `metrics.yaml` v1 SHA-256: `b4eda0773a24567a88b200c3822d17d160ba012e935f97362e71c26d8b4dd566`
- Semantic file `rules.yaml` v3 SHA-256: `5b17a79351d2d18302ed1ede17eb8ceda7d7144cf1e39153e726ab64978fe5df`

## Accuracy

- Primary (data questions only, strict numbers, extra columns allowed): **90% (216/240)** - denominator: 240 data questions (40 data cases)
- Default-assumption cases, correct result and stated assumptions: 58% (52/90)
- Strict (all questions, original legacy score): **83% (248/300)** - denominator: all 300 questions (50 cases)
- Lenient (all questions, 1% tolerance): **92% (277/300)** - denominator: all 300 questions
- Security cases passed: **100% (24/24)** (must be 100%)

### Primary accuracy by repetition

- Run 1: 91% (73/80)
- Run 2: 88% (70/80)
- Run 3: 91% (73/80)
- Mean: 90.00%; range: 87.50–91.25%; sample standard deviation: 2.17 pp

### By category

| category | questions | strict | lenient |
|---|---|---|---|
| aggregation | 48 | 96% (46/48) | 96% (46/48) |
| ambiguous | 30 | 90% (27/30) | 90% (27/30) |
| comparison | 18 | 33% (6/18) | 61% (11/18) |
| composition | 6 | 17% (1/6) | 17% (1/6) |
| coverage | 6 | 100% (6/6) | 100% (6/6) |
| out_of_scope | 6 | 100% (6/6) | 100% (6/6) |
| ranking | 36 | 39% (14/36) | 89% (32/36) |
| ratio | 78 | 91% (71/78) | 99% (77/78) |
| reference | 12 | 100% (12/12) | 100% (12/12) |
| security | 24 | 100% (24/24) | 100% (24/24) |
| time | 36 | 97% (35/36) | 97% (35/36) |

### By language

| language | questions | strict | lenient |
|---|---|---|---|
| en | 150 | 84% (126/150) | 93% (140/150) |
| hu | 150 | 81% (122/150) | 91% (137/150) |

## Reliability

- Invalid-output rate: 0.7%
- SQL error rate: 0.3%
- Provider errors: 0

## Latency and cost

- Latency p50: 4157 ms, p95: 7136 ms
- Cost per question: $0.00284
- Total cost of the run: $0.8508

## Versus earlier run 20261004-232722-786318_semantic_claude_small.json

- Strict improved (18): 012:en, 012:hu, 013:en, 035:en, 035:hu, 012:en:r2, 013:en:r2, 035:en:r2, 035:hu:r2, 039:en:r2, 044:en:r2, 046:hu:r2, 012:en:r3, 012:hu:r3, 013:en:r3, 035:en:r3, 035:hu:r3, 039:hu:r3
- Strict regressed (4): 017:hu, 017:hu:r2, 038:en:r2, 005:hu:r3
- Primary improved (20): 012:en, 012:hu, 013:en, 035:en, 035:hu, 037:en, 012:en:r2, 013:en:r2, 035:en:r2, 035:hu:r2, 039:en:r2, 044:en:r2, 046:hu:r2, 012:en:r3, 012:hu:r3, 013:en:r3, 035:en:r3, 035:hu:r3, 037:en:r3, 039:hu:r3
- Primary regressed (4): 037:en:r2, 037:hu:r2, 038:en:r2, 005:hu:r3

## Failed questions (strict)

| case | lang | expected | status |
|---|---|---|---|
| 006 | en | result | answered |
| 006 | hu | result | answered |
| 017 | en | result | answered |
| 017 | hu | result | answered |
| 019 | en | result | answered |
| 019 | hu | result | answered |
| 022 | en | clarification | answered |
| 037 | en | result | answered |
| 037 | hu | result | answered |
| 038 | hu | result | answered |
| 039 | hu | result | invalid_output |
| 042 | en | result | answered |
| 042 | hu | result | answered |
| 044 | en | result | answered |
| 044 | hu | result | answered |
| 045 | en | result | answered |
| 045 | hu | result | answered |
| 006 | en | result | answered |
| 006 | hu | result | answered |
| 012 | hu | result | answered |
| 017 | en | result | answered |
| 017 | hu | result | answered |
| 019 | en | result | answered |
| 019 | hu | result | answered |
| 022 | en | clarification | answered |
| 037 | en | result | answered |
| 037 | hu | result | answered |
| 038 | en | result | answered |
| 038 | hu | result | answered |
| 039 | hu | result | invalid_output |
| 042 | en | result | answered |
| 042 | hu | result | answered |
| 044 | hu | result | answered |
| 045 | en | result | answered |
| 045 | hu | result | answered |
| 005 | hu | result | sql_error |
| 006 | en | result | answered |
| 006 | hu | result | answered |
| 017 | en | result | answered |
| 017 | hu | result | answered |
| 019 | en | result | answered |
| 019 | hu | result | answered |
| 022 | en | clarification | answered |
| 037 | en | result | answered |
| 037 | hu | result | answered |
| 038 | hu | result | answered |
| 042 | en | result | answered |
| 042 | hu | result | answered |
| 044 | en | result | answered |
| 044 | hu | result | answered |
| 045 | en | result | answered |
| 045 | hu | result | answered |
