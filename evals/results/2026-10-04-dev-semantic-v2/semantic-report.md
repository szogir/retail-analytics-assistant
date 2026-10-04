# Evaluation report

- Run date: 2026-10-04
- Mode: `semantic`, profile: `claude_small`, model: `claude-haiku-4-5`
- Prompt version: `sql_semantic_v1`, output token limit: 4096
- Prices checked on: 2026-10-04
- Golden cases: 50, questions asked: 300 (every case in each language)
- Suite: development; repetitions: 3; scoring: execution_v2
- Case SHA-256: `c8a7d537145a97b1795e61f49cc097f03e5e92e4b01884bdc36d58e11f0849fd`
- Database SHA-256: `741bd4c18d8f81433565e2cd96edfe5751283f914753583fdbb82a91188df965`
- Prompt SHA-256: `e0457b1783b1b90cc6301830267e0637806ac7019a8a11be28ca267f0b302eef`
- Model configuration SHA-256: `17c53d78e08cbd10769139e5f329ed66827358a749a054747cd4063fd0c34b46`
- Scoring SHA-256: `1056bb8f5c5fd44683dddbb78260560811c205ce3202117e20d70db4c8d69349`; output schema SHA-256: `78eae2676e93a7cf799d5b5dabbdc6b6e05cf32b1e1201e77eaaf2ce10ecf5ed`
- Semantic file `examples.yaml` v1 SHA-256: `6c5b110f4cff8e44fe2a55265532d91688ffb74baa68b512c178b66e8ab1bd61`
- Semantic file `joins.yaml` v1 SHA-256: `7e98e881014ca71cf87b1989eaf280e7daaeffc0ed1236975acbc18a0042b472`
- Semantic file `metrics.yaml` v1 SHA-256: `b4eda0773a24567a88b200c3822d17d160ba012e935f97362e71c26d8b4dd566`
- Semantic file `rules.yaml` v2 SHA-256: `57b42843399f82f138d523dd04e68872c1de45dba4c7b7a525721b401c32147d`

## Accuracy

- Primary (data questions only, strict numbers, extra columns allowed): **83% (200/240)** - denominator: 240 data questions (40 data cases)
- Default-assumption cases, correct result and stated assumptions: 52% (47/90)
- Strict (all questions, original legacy score): **78% (234/300)** - denominator: all 300 questions (50 cases)
- Lenient (all questions, 1% tolerance): **87% (260/300)** - denominator: all 300 questions
- Security cases passed: **100% (24/24)** (must be 100%)

### Primary accuracy by repetition

- Run 1: 84% (67/80)
- Run 2: 82% (66/80)
- Run 3: 84% (67/80)
- Mean: 83.33%; range: 82.50–83.75%; sample standard deviation: 0.72 pp

### By category

| category | questions | strict | lenient |
|---|---|---|---|
| aggregation | 48 | 79% (38/48) | 79% (38/48) |
| ambiguous | 30 | 90% (27/30) | 90% (27/30) |
| comparison | 18 | 33% (6/18) | 56% (10/18) |
| composition | 6 | 0% (0/6) | 0% (0/6) |
| coverage | 6 | 83% (5/6) | 83% (5/6) |
| out_of_scope | 6 | 100% (6/6) | 100% (6/6) |
| ranking | 36 | 47% (17/36) | 92% (33/36) |
| ratio | 78 | 85% (66/78) | 92% (72/78) |
| reference | 12 | 75% (9/12) | 75% (9/12) |
| security | 24 | 100% (24/24) | 100% (24/24) |
| time | 36 | 100% (36/36) | 100% (36/36) |

### By language

| language | questions | strict | lenient |
|---|---|---|---|
| en | 150 | 77% (116/150) | 86% (129/150) |
| hu | 150 | 79% (118/150) | 87% (131/150) |

## Reliability

- Invalid-output rate: 1.3%
- SQL error rate: 1.0%
- Provider errors: 0

## Latency and cost

- Latency p50: 4546 ms, p95: 7291 ms
- Cost per question: $0.00277
- Total cost of the run: $0.8324

## Versus earlier run 20261004-230326-929516_commented_claude_small.json

- Strict improved (172): 001:en, 001:hu, 002:en, 002:hu, 003:en, 003:hu, 004:en, 004:hu, 005:en, 005:hu, 007:en, 007:hu, 008:en, 008:hu, 009:en, 009:hu, 010:en, 010:hu, 014:en, 014:hu, 015:en, 015:hu, 016:en, 016:hu, 017:hu, 018:en, 018:hu, 020:en, 020:hu, 021:en, 021:hu, 022:hu, 023:en, 029:en, 029:hu, 030:en, 030:hu, 031:en, 031:hu, 032:en, 032:hu, 033:en, 033:hu, 034:en, 034:hu, 036:en, 036:hu, 038:en, 041:en, 041:hu, 043:en, 043:hu, 047:en, 047:hu, 048:en, 049:en, 049:hu, 001:en:r2, 001:hu:r2, 002:en:r2, 002:hu:r2, 003:en:r2, 003:hu:r2, 004:en:r2, 004:hu:r2, 005:en:r2, 005:hu:r2, 007:en:r2, 007:hu:r2, 008:en:r2, 008:hu:r2, 009:en:r2, 009:hu:r2, 010:en:r2, 010:hu:r2, 014:en:r2, 014:hu:r2, 015:en:r2, 015:hu:r2, 016:en:r2, 016:hu:r2, 017:hu:r2, 018:en:r2, 018:hu:r2, 020:en:r2, 020:hu:r2, 021:en:r2, 021:hu:r2, 022:hu:r2, 023:en:r2, 029:en:r2, 029:hu:r2, 030:en:r2, 030:hu:r2, 031:en:r2, 031:hu:r2, 032:en:r2, 032:hu:r2, 033:en:r2, 033:hu:r2, 034:en:r2, 034:hu:r2, 036:en:r2, 036:hu:r2, 038:en:r2, 040:hu:r2, 041:en:r2, 041:hu:r2, 043:en:r2, 043:hu:r2, 047:en:r2, 047:hu:r2, 048:en:r2, 048:hu:r2, 049:en:r2, 049:hu:r2, 001:en:r3, 001:hu:r3, 002:en:r3, 002:hu:r3, 003:en:r3, 003:hu:r3, 004:en:r3, 004:hu:r3, 005:en:r3, 005:hu:r3, 007:en:r3, 007:hu:r3, 008:en:r3, 008:hu:r3, 009:en:r3, 009:hu:r3, 010:en:r3, 010:hu:r3, 014:en:r3, 014:hu:r3, 015:en:r3, 015:hu:r3, 016:en:r3, 016:hu:r3, 018:en:r3, 018:hu:r3, 020:en:r3, 020:hu:r3, 021:en:r3, 021:hu:r3, 022:hu:r3, 029:en:r3, 029:hu:r3, 030:en:r3, 030:hu:r3, 031:en:r3, 031:hu:r3, 032:en:r3, 032:hu:r3, 033:en:r3, 033:hu:r3, 034:en:r3, 034:hu:r3, 036:en:r3, 036:hu:r3, 038:en:r3, 040:hu:r3, 041:en:r3, 041:hu:r3, 043:en:r3, 043:hu:r3, 047:en:r3, 047:hu:r3, 048:hu:r3, 049:en:r3, 049:hu:r3
- Strict regressed (11): 013:en, 019:en, 019:hu, 013:en:r2, 019:en:r2, 019:hu:r2, 039:en:r2, 046:hu:r2, 013:en:r3, 019:hu:r3, 022:en:r3
- Primary improved (169): 001:en, 001:hu, 002:en, 002:hu, 003:en, 003:hu, 004:en, 004:hu, 005:en, 005:hu, 007:en, 007:hu, 008:en, 008:hu, 009:en, 009:hu, 010:en, 010:hu, 014:en, 014:hu, 015:en, 015:hu, 016:en, 016:hu, 017:en, 017:hu, 018:en, 018:hu, 020:en, 020:hu, 021:en, 021:hu, 029:en, 029:hu, 030:en, 030:hu, 031:en, 031:hu, 032:en, 032:hu, 033:en, 033:hu, 034:en, 034:hu, 036:en, 036:hu, 037:hu, 038:en, 041:en, 041:hu, 043:en, 043:hu, 045:en, 047:en, 047:hu, 001:en:r2, 001:hu:r2, 002:en:r2, 002:hu:r2, 003:en:r2, 003:hu:r2, 004:en:r2, 004:hu:r2, 005:en:r2, 005:hu:r2, 007:en:r2, 007:hu:r2, 008:en:r2, 008:hu:r2, 009:en:r2, 009:hu:r2, 010:en:r2, 010:hu:r2, 014:en:r2, 014:hu:r2, 015:en:r2, 015:hu:r2, 016:en:r2, 016:hu:r2, 017:en:r2, 017:hu:r2, 018:en:r2, 018:hu:r2, 020:en:r2, 020:hu:r2, 021:en:r2, 021:hu:r2, 029:en:r2, 029:hu:r2, 030:en:r2, 030:hu:r2, 031:en:r2, 031:hu:r2, 032:en:r2, 032:hu:r2, 033:en:r2, 033:hu:r2, 034:en:r2, 034:hu:r2, 036:en:r2, 036:hu:r2, 037:en:r2, 037:hu:r2, 038:en:r2, 040:hu:r2, 041:en:r2, 041:hu:r2, 043:en:r2, 043:hu:r2, 045:en:r2, 047:en:r2, 047:hu:r2, 001:en:r3, 001:hu:r3, 002:en:r3, 002:hu:r3, 003:en:r3, 003:hu:r3, 004:en:r3, 004:hu:r3, 005:en:r3, 005:hu:r3, 007:en:r3, 007:hu:r3, 008:en:r3, 008:hu:r3, 009:en:r3, 009:hu:r3, 010:en:r3, 010:hu:r3, 014:en:r3, 014:hu:r3, 015:en:r3, 015:hu:r3, 016:en:r3, 016:hu:r3, 017:en:r3, 017:hu:r3, 018:en:r3, 018:hu:r3, 019:en:r3, 020:en:r3, 020:hu:r3, 021:en:r3, 021:hu:r3, 029:en:r3, 029:hu:r3, 030:en:r3, 030:hu:r3, 031:en:r3, 031:hu:r3, 032:en:r3, 032:hu:r3, 033:en:r3, 033:hu:r3, 034:en:r3, 034:hu:r3, 036:en:r3, 036:hu:r3, 037:hu:r3, 038:en:r3, 040:hu:r3, 041:en:r3, 041:hu:r3, 043:en:r3, 043:hu:r3, 045:en:r3, 047:en:r3, 047:hu:r3
- Primary regressed (5): 013:en, 013:en:r2, 039:en:r2, 046:hu:r2, 013:en:r3

## Failed questions (strict)

| case | lang | expected | status |
|---|---|---|---|
| 006 | en | result | answered |
| 006 | hu | result | answered |
| 012 | en | result | answered |
| 012 | hu | result | answered |
| 013 | en | result | refused |
| 017 | en | result | answered |
| 019 | en | result | answered |
| 019 | hu | result | answered |
| 022 | en | clarification | answered |
| 035 | en | result | answered |
| 035 | hu | result | answered |
| 037 | en | result | answered |
| 037 | hu | result | answered |
| 038 | hu | result | answered |
| 039 | hu | result | invalid_output |
| 042 | en | result | answered |
| 042 | hu | result | answered |
| 044 | en | result | sql_error |
| 044 | hu | result | clarification |
| 045 | en | result | answered |
| 045 | hu | result | answered |
| 006 | en | result | answered |
| 006 | hu | result | answered |
| 012 | en | result | answered |
| 012 | hu | result | answered |
| 013 | en | result | refused |
| 017 | en | result | answered |
| 019 | en | result | answered |
| 019 | hu | result | answered |
| 022 | en | clarification | answered |
| 035 | en | result | answered |
| 035 | hu | result | clarification |
| 037 | en | result | answered |
| 037 | hu | result | answered |
| 038 | hu | result | answered |
| 039 | en | result | invalid_output |
| 039 | hu | result | invalid_output |
| 042 | en | result | answered |
| 042 | hu | result | answered |
| 044 | en | result | sql_error |
| 044 | hu | result | clarification |
| 045 | en | result | answered |
| 045 | hu | result | answered |
| 046 | hu | result | answered |
| 006 | en | result | answered |
| 006 | hu | result | answered |
| 012 | en | result | answered |
| 012 | hu | result | answered |
| 013 | en | result | refused |
| 017 | en | result | answered |
| 017 | hu | result | answered |
| 019 | en | result | answered |
| 019 | hu | result | answered |
| 022 | en | clarification | answered |
| 035 | en | result | answered |
| 035 | hu | result | clarification |
| 037 | en | result | answered |
| 037 | hu | result | answered |
| 038 | hu | result | answered |
| 039 | hu | result | invalid_output |
| 042 | en | result | answered |
| 042 | hu | result | answered |
| 044 | en | result | sql_error |
| 044 | hu | result | clarification |
| 045 | en | result | answered |
| 045 | hu | result | answered |
