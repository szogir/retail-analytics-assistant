# Evaluation report

- Run date: 2026-10-04
- Mode: `naive`, profile: `claude_small`, model: `claude-haiku-4-5`
- Prompt version: `sql_naive_v1`, output token limit: 4096
- Prices checked on: 2026-10-04
- Golden cases: 28, questions asked: 56 (every case in each language)

## Accuracy

- Strict: **27% (15/56)**
- Lenient: **36% (20/56)**
- Security cases passed: **100% (8/8)** (must be 100%)

### By category

| category | questions | strict | lenient |
|---|---|---|---|
| aggregation | 8 | 0% (0/8) | 0% (0/8) |
| ambiguous | 4 | 25% (1/4) | 25% (1/4) |
| out_of_scope | 2 | 100% (2/2) | 100% (2/2) |
| ranking | 8 | 0% (0/8) | 50% (4/8) |
| ratio | 16 | 0% (0/16) | 6% (1/16) |
| reference | 4 | 100% (4/4) | 100% (4/4) |
| security | 8 | 100% (8/8) | 100% (8/8) |
| time | 6 | 0% (0/6) | 0% (0/6) |

### By language

| language | questions | strict | lenient |
|---|---|---|---|
| en | 28 | 25% (7/28) | 36% (10/28) |
| hu | 28 | 29% (8/28) | 36% (10/28) |

## Reliability

- Invalid-output rate: 0.0%
- SQL error rate: 7.1%
- Provider errors: 0

## Latency and cost

- Latency p50: 3960 ms, p95: 6372 ms
- Cost per question: $0.00299
- Total cost of the run: $0.1673

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
| 004 | en | result | answered |
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
| 018 | hu | result | sql_error |
| 019 | en | result | answered |
| 019 | hu | result | answered |
| 020 | en | result | answered |
| 020 | hu | result | sql_error |
| 021 | en | result | answered |
| 021 | hu | result | answered |
| 022 | en | clarification | answered |
| 022 | hu | clarification | answered |
| 023 | en | clarification | answered |
