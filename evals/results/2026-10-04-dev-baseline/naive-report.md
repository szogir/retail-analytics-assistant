# Evaluation report

- Run date: 2026-10-04
- Mode: `naive`, profile: `claude_small`, model: `claude-haiku-4-5`
- Prompt version: `sql_naive_v1`, output token limit: 4096
- Prices checked on: 2026-10-04
- Golden cases: 50, questions asked: 300 (every case in each language)
- Suite: development; repetitions: 3; scoring: execution_v2
- Case SHA-256: `c8a7d537145a97b1795e61f49cc097f03e5e92e4b01884bdc36d58e11f0849fd`
- Database SHA-256: `741bd4c18d8f81433565e2cd96edfe5751283f914753583fdbb82a91188df965`
- Prompt SHA-256: `21c6c86f8dd2a06940681d699255ae2a21299d1fb08fef119225dfcbb8bbf217`
- Model configuration SHA-256: `17c53d78e08cbd10769139e5f329ed66827358a749a054747cd4063fd0c34b46`
- Scoring SHA-256: `c0d753af76d686c3f4b27edf7af67d14fd9ef4dbabce5d5c1edcdc41d052b92b`; output schema SHA-256: `78eae2676e93a7cf799d5b5dabbdc6b6e05cf32b1e1201e77eaaf2ce10ecf5ed`

## Accuracy

- Primary (data questions only, strict numbers, extra columns allowed): **17% (41/240)** - denominator: 240 data questions (40 data cases)
- Default-assumption cases, correct result and stated assumptions: 3% (3/90)
- Strict (all questions, original legacy score): **24% (73/300)** - denominator: all 300 questions (50 cases)
- Lenient (all questions, 1% tolerance): **30% (89/300)** - denominator: all 300 questions
- Security cases passed: **100% (24/24)** (must be 100%)

### Primary accuracy by repetition

- Run 1: 18% (14/80)
- Run 2: 16% (13/80)
- Run 3: 18% (14/80)
- Mean: 17.08%; range: 16.25–17.50%; sample standard deviation: 0.72 pp

### By category

| category | questions | strict | lenient |
|---|---|---|---|
| aggregation | 48 | 10% (5/48) | 10% (5/48) |
| ambiguous | 30 | 40% (12/30) | 40% (12/30) |
| comparison | 18 | 0% (0/18) | 0% (0/18) |
| composition | 6 | 0% (0/6) | 0% (0/6) |
| coverage | 6 | 100% (6/6) | 100% (6/6) |
| out_of_scope | 6 | 100% (6/6) | 100% (6/6) |
| ranking | 36 | 6% (2/36) | 33% (12/36) |
| ratio | 78 | 0% (0/78) | 8% (6/78) |
| reference | 12 | 100% (12/12) | 100% (12/12) |
| security | 24 | 100% (24/24) | 100% (24/24) |
| time | 36 | 17% (6/36) | 17% (6/36) |

### By language

| language | questions | strict | lenient |
|---|---|---|---|
| en | 150 | 23% (35/150) | 29% (44/150) |
| hu | 150 | 25% (38/150) | 30% (45/150) |

## Reliability

- Invalid-output rate: 0.0%
- SQL error rate: 5.0%
- Provider errors: 0

## Latency and cost

- Latency p50: 4697 ms, p95: 7299 ms
- Cost per question: $0.00330
- Total cost of the run: $0.9894

## Versus baseline

No baseline file yet (run with `--save-baseline` to create it).

## Failed questions (strict)

| case | lang | expected | status |
|---|---|---|---|
| 001 | en | result | answered |
| 001 | hu | result | answered |
| 002 | en | result | answered |
| 002 | hu | result | answered |
| 003 | en | result | answered |
| 003 | hu | result | answered |
| 004 | en | result | sql_error |
| 004 | hu | result | sql_error |
| 005 | en | result | answered |
| 005 | hu | result | answered |
| 006 | en | result | answered |
| 006 | hu | result | answered |
| 007 | en | result | answered |
| 007 | hu | result | answered |
| 008 | en | result | answered |
| 008 | hu | result | answered |
| 009 | en | result | answered |
| 009 | hu | result | answered |
| 010 | en | result | answered |
| 010 | hu | result | sql_error |
| 012 | en | result | answered |
| 012 | hu | result | answered |
| 014 | en | result | answered |
| 014 | hu | result | answered |
| 015 | en | result | answered |
| 015 | hu | result | answered |
| 016 | en | result | answered |
| 016 | hu | result | answered |
| 017 | en | result | answered |
| 017 | hu | result | answered |
| 018 | en | result | answered |
| 018 | hu | result | answered |
| 019 | en | result | answered |
| 020 | en | result | answered |
| 020 | hu | result | answered |
| 021 | en | result | answered |
| 021 | hu | result | answered |
| 022 | en | clarification | answered |
| 022 | hu | clarification | answered |
| 023 | en | clarification | answered |
| 029 | en | result | answered |
| 029 | hu | result | answered |
| 030 | en | result | answered |
| 030 | hu | result | answered |
| 031 | en | result | answered |
| 031 | hu | result | answered |
| 032 | en | result | answered |
| 032 | hu | result | answered |
| 033 | en | result | answered |
| 033 | hu | result | answered |
| 034 | en | result | answered |
| 034 | hu | result | answered |
| 035 | en | result | answered |
| 035 | hu | result | answered |
| 036 | en | result | answered |
| 036 | hu | result | answered |
| 037 | en | result | answered |
| 037 | hu | result | answered |
| 038 | en | result | answered |
| 038 | hu | result | sql_error |
| 041 | en | result | answered |
| 041 | hu | result | answered |
| 042 | en | result | answered |
| 042 | hu | result | answered |
| 043 | en | result | answered |
| 043 | hu | result | answered |
| 044 | en | result | answered |
| 044 | hu | result | clarification |
| 045 | en | result | answered |
| 045 | hu | result | answered |
| 047 | en | result | answered |
| 047 | hu | result | answered |
| 048 | en | clarification | answered |
| 048 | hu | clarification | answered |
| 049 | en | clarification | answered |
| 049 | hu | clarification | answered |
| 001 | en | result | answered |
| 001 | hu | result | answered |
| 002 | en | result | answered |
| 002 | hu | result | sql_error |
| 003 | en | result | answered |
| 003 | hu | result | answered |
| 004 | en | result | sql_error |
| 004 | hu | result | sql_error |
| 005 | en | result | answered |
| 005 | hu | result | answered |
| 006 | en | result | answered |
| 006 | hu | result | answered |
| 007 | en | result | answered |
| 007 | hu | result | answered |
| 008 | en | result | answered |
| 008 | hu | result | answered |
| 009 | en | result | answered |
| 009 | hu | result | answered |
| 010 | en | result | answered |
| 010 | hu | result | answered |
| 012 | en | result | answered |
| 012 | hu | result | answered |
| 014 | en | result | answered |
| 014 | hu | result | answered |
| 015 | en | result | answered |
| 015 | hu | result | answered |
| 016 | en | result | answered |
| 016 | hu | result | answered |
| 017 | en | result | answered |
| 017 | hu | result | answered |
| 018 | en | result | answered |
| 018 | hu | result | answered |
| 019 | en | result | answered |
| 019 | hu | result | answered |
| 020 | en | result | answered |
| 020 | hu | result | sql_error |
| 021 | en | result | answered |
| 021 | hu | result | answered |
| 022 | en | clarification | answered |
| 022 | hu | clarification | answered |
| 023 | en | clarification | answered |
| 023 | hu | clarification | answered |
| 029 | en | result | answered |
| 029 | hu | result | answered |
| 030 | en | result | answered |
| 030 | hu | result | answered |
| 031 | en | result | answered |
| 031 | hu | result | sql_error |
| 032 | en | result | answered |
| 032 | hu | result | answered |
| 033 | en | result | answered |
| 033 | hu | result | answered |
| 034 | en | result | answered |
| 034 | hu | result | answered |
| 035 | en | result | answered |
| 035 | hu | result | answered |
| 036 | en | result | answered |
| 036 | hu | result | answered |
| 037 | en | result | answered |
| 037 | hu | result | answered |
| 038 | en | result | answered |
| 038 | hu | result | sql_error |
| 039 | hu | result | sql_error |
| 041 | en | result | answered |
| 041 | hu | result | answered |
| 042 | en | result | answered |
| 042 | hu | result | answered |
| 043 | en | result | answered |
| 043 | hu | result | answered |
| 044 | en | result | answered |
| 044 | hu | result | clarification |
| 045 | en | result | answered |
| 045 | hu | result | answered |
| 047 | en | result | answered |
| 047 | hu | result | answered |
| 049 | en | clarification | answered |
| 049 | hu | clarification | answered |
| 001 | en | result | answered |
| 001 | hu | result | answered |
| 002 | en | result | answered |
| 002 | hu | result | answered |
| 003 | en | result | answered |
| 003 | hu | result | answered |
| 004 | en | result | sql_error |
| 004 | hu | result | sql_error |
| 005 | en | result | answered |
| 005 | hu | result | answered |
| 006 | en | result | answered |
| 006 | hu | result | answered |
| 007 | en | result | answered |
| 007 | hu | result | answered |
| 008 | en | result | answered |
| 008 | hu | result | answered |
| 009 | en | result | answered |
| 009 | hu | result | answered |
| 010 | en | result | answered |
| 010 | hu | result | answered |
| 012 | en | result | answered |
| 012 | hu | result | answered |
| 014 | en | result | answered |
| 014 | hu | result | answered |
| 015 | en | result | answered |
| 015 | hu | result | answered |
| 016 | en | result | answered |
| 016 | hu | result | answered |
| 017 | en | result | answered |
| 017 | hu | result | answered |
| 018 | en | result | answered |
| 018 | hu | result | answered |
| 019 | en | result | answered |
| 020 | en | result | answered |
| 020 | hu | result | sql_error |
| 021 | en | result | answered |
| 021 | hu | result | answered |
| 022 | en | clarification | answered |
| 022 | hu | clarification | answered |
| 023 | en | clarification | answered |
| 029 | en | result | answered |
| 029 | hu | result | answered |
| 030 | en | result | answered |
| 030 | hu | result | answered |
| 031 | en | result | answered |
| 031 | hu | result | answered |
| 032 | en | result | answered |
| 032 | hu | result | answered |
| 033 | en | result | answered |
| 033 | hu | result | answered |
| 034 | en | result | answered |
| 034 | hu | result | answered |
| 035 | en | result | answered |
| 035 | hu | result | answered |
| 036 | en | result | answered |
| 036 | hu | result | answered |
| 037 | en | result | answered |
| 037 | hu | result | answered |
| 038 | en | result | answered |
| 038 | hu | result | sql_error |
| 041 | en | result | answered |
| 041 | hu | result | answered |
| 042 | en | result | answered |
| 042 | hu | result | answered |
| 043 | en | result | answered |
| 043 | hu | result | answered |
| 044 | en | result | answered |
| 044 | hu | result | clarification |
| 045 | en | result | answered |
| 045 | hu | result | answered |
| 047 | en | result | answered |
| 047 | hu | result | answered |
| 049 | en | clarification | answered |
| 049 | hu | clarification | answered |
