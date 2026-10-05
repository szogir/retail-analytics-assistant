# Case-level v2 vs v3 (6 questions per case = 2 languages x 3 repetitions)

## Main metric (preregistered)

Data cases (`result`, `result_scoped`) use the primary score: extra columns allowed,
relative tolerance 1e-6. Non-data cases (`clarification`, `refusal`) use the strict score.
Source: the `primary` field of the two run files. All other cases score 6/6 in both runs.

| case | v2 main | v3 main | change |
|---|---|---|---|
| 005 | 6/6 | 5/6 | regressed |
| 012 | 0/6 | 5/6 | improved |
| 013 | 3/6 | 6/6 | improved |
| 035 | 0/6 | 6/6 | improved |
| 038 | 3/6 | 2/6 | regressed |
| 039 | 2/6 | 4/6 | improved |
| 044 | 0/6 | 1/6 | improved |
| 046 | 5/6 | 6/6 | improved |

Cases below 6/6 in v3 on the main metric (the real failures):

| case | v3 main | note |
|---|---|---|
| 042 | 0/6 | model limit (LAG computed before the WHERE filter) |
| 044 | 1/6 | model limit |
| 038 | 2/6 | unstable |
| 045 | 3/6 | EN 3/3, HU 0/3: the Hungarian answer rounds to 2 decimals |
| 022 | 3/6 | clarification case, unstable |
| 037 | 4/6 | |
| 039 | 4/6 | unstable |
| 005 | 5/6 | unstable |
| 012 | 5/6 | |

Cases 006, 017 and 019 are 6/6 on the main metric; they only fail the legacy strict score
(see below). Totals over all 300 questions: v2 257, v3 273 main-metric passes.

## Legacy strict metric (superseded, kept for history)

Strict requires an exact column set, so it fails correct answers with extra columns
(006, 017, 019, 037, 045 are 0/6 here but not on the main metric). Do not use it to decide
which cases are failing.

| case | v2 strict | v3 strict | change |
|---|---|---|---|
| 005 | 6/6 | 5/6 | regressed |
| 012 | 0/6 | 5/6 | improved |
| 013 | 3/6 | 6/6 | improved |
| 017 | 2/6 | 0/6 | regressed |
| 035 | 0/6 | 6/6 | improved |
| 038 | 3/6 | 2/6 | regressed |
| 039 | 2/6 | 4/6 | improved |
| 044 | 0/6 | 1/6 | improved |
| 046 | 5/6 | 6/6 | improved |
