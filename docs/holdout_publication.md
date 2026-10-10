# Publishing the held-out suite

The held-out suite was sealed during development and is spent after the confirmatory run
([Decision 16](decisions.md#decision-16-confirmatory-holdout-result-2026-10-05)). Publishing
its cases and run files lets anyone check that they are exactly the files that
[`evals/holdout_manifest.json`](../evals/holdout_manifest.json) committed to.

**Status: published** in commit `7c33b49` (2026-10-10); `--verify` on the published folder
ends with `verified: yes` (manifest digest `91b689f8...`). The database is published as the
[`data-v1` Release](https://github.com/szogir/retail-analytics-assistant/releases/tag/data-v1)
attachment `retail.duckdb` (step 5; SHA-256 `741bd4c1...`, checked against the uploaded file).
The steps below record how the publication was done.

## What is published and what is not

Only the hashed files and the run files are published; working notes are not.

| published | where |
|---|---|
| the held-out case files (`*.yaml`) and `oracles.py`, byte-identical | `evals/holdout_published/` |
| the three holdout run files and the holdout reports | `evals/results/2026-10-05-holdout/` |

Not published, whatever the folder contains: audit reports, changelogs, `review.md`, candidate
files, everything in the `artifacts/` subfolder, backups and other working files.

Why byte-identical: the manifest holds the SHA-256 of each file's raw bytes. Any conversion of
line endings or encoding changes the hash and makes the check fail. That is why `.gitattributes`
marks both folders `-text` and `.pre-commit-config.yaml` and the ruff configuration exclude them:
no tool may reformat these files.

Why no mirroring (`robocopy /MIR`, `/E`): that would also copy subfolders such as `artifacts/`.
The copy uses file patterns on the top-level folder only. `--verify` hashes every `*.yaml` in the
folder, so no other YAML file may be there.

## Steps

All commands are for PowerShell, run in the repository root. `$src` is the sealed suite folder
(the one `HOLDOUT_DIR` points to).

### 1. Copy the hashed files, byte-identical

```powershell
$src = $env:HOLDOUT_DIR
robocopy $src evals\holdout_published *.yaml oracles.py /R:1 /W:1
```

Do not add `/MIR`, `/E`, `/S` or `/PURGE`. `robocopy` copies the bytes unchanged. Afterwards
the folder must contain exactly the case files and `oracles.py` and nothing else:

```powershell
Get-ChildItem evals\holdout_published | Select-Object Name
(Get-ChildItem evals\holdout_published -Filter *.yaml).Count   # 50 case files
```

### 2. Copy the run files and reports

Create the folder and copy only the three holdout run files and the holdout reports, by name:

```powershell
New-Item -ItemType Directory -Force evals\results\2026-10-05-holdout | Out-Null
# run files (naive, commented, semantic) and the reports, copied one by one:
Copy-Item "<run folder>\20261005-164447*naive*.json"     evals\results\2026-10-05-holdout\
Copy-Item "<run folder>\20261005-171533*commented*.json" evals\results\2026-10-05-holdout\
Copy-Item "<run folder>\20261005-175902*semantic*.json"  evals\results\2026-10-05-holdout\
Copy-Item "<run folder>\<each holdout report>.md"        evals\results\2026-10-05-holdout\
```

The paired-analysis JSON files may be UTF-16 (a PowerShell redirect writes UTF-16). Convert
those, and only those, to UTF-8 without a byte-order mark:

```powershell
$utf8 = New-Object System.Text.UTF8Encoding($false)
Get-ChildItem evals\results\2026-10-05-holdout\paired-*.json | ForEach-Object {
    $text = [System.IO.File]::ReadAllText($_.FullName)          # detects the BOM
    [System.IO.File]::WriteAllText($_.FullName, $text, $utf8)
}
```

### 3. Regenerate the database and check its hash

```powershell
uv run python -m data_gen.generate     # only in a clone; never replace the original database
(Get-FileHash data\retail.duckdb -Algorithm SHA256).Hash.ToLower()
# 741bd4c18d8f81433565e2cd96edfe5751283f914753583fdbb82a91188df965
```

### 4. Verify the commitment, then scan before committing

```powershell
uv run python -m evals.validate_suite --suite holdout --verify --holdout-dir evals\holdout_published
```

It must end with `holdout: manifest_sha256=...; verified: yes` (the manifest digest recorded in
Decision 16 starts with `91b689f8`). `suite_directory` normally refuses a holdout folder inside the
repository; the published copy `evals/holdout_published` is the one exception. Then stage the two folders (staging is
not committing) and scan what would be published for words that must not appear:

```powershell
git add evals/holdout_published evals/results/2026-10-05-holdout
git grep --cached -n -i -E "co-authored|generated with|c:\\users|@gmail|api[_-]?key|sk-ant" -- evals/holdout_published evals/results/2026-10-05-holdout
```

No output means nothing was found. The model name `claude-haiku-4-5` in the run files is
expected and is not a finding. Add your own terms (for example an employer or a real brand name)
to the pattern; they are deliberately not listed here. Check also that the staged file list is
what step 1 and 2 produced:

```powershell
git diff --cached --stat -- evals/holdout_published evals/results/2026-10-05-holdout
```

Then run the local pre-publication check.

Commit only when the verification and both scans are clean.

### 5. Publish the database as a release attachment

The generator is seeded and byte-identical in a fresh clone on Windows, but a Linux rebuild
(DuckDB 1.5.6) gives a different digest. The attachment is therefore the reference copy for
other platforms, and the CI downloads it. Upload the original `data\retail.duckdb`, never a
regenerated one, and create the release before pushing the CI change:

```powershell
gh release create data-v1 data\retail.duckdb --title "Synthetic retail database" `
  --notes "SHA-256: 741bd4c18d8f81433565e2cd96edfe5751283f914753583fdbb82a91188df965"
```

## After publication

- The README links the published folders, the verification command and the `data-v1`
  database Release.
- The published copy is regression data. The external working folder is not published and
  stays private.

## Continuous integration

The CI (`.github/workflows/ci.yml`) checks the commitment on every push:

1. downloads `retail.duckdb` from the `data-v1` Release and checks its SHA-256,
2. runs `uv run python -m evals.validate_suite --suite holdout --verify --holdout-dir
   evals/holdout_published`,
3. runs `uv run pytest -m "not live and not review"` with `HOLDOUT_DIR` set to the published
   folder, so the holdout-marked tests run on it.

**Platform decision.** The byte-identical rebuild of `data/retail.duckdb` (SHA-256
`741bd4c1...`) holds on Windows only: a fresh clone on Linux (python:3.12-slim, DuckDB 1.5.6,
`uv sync --frozen`) produced `8aed83ad...`. The file's bytes are platform-dependent, the
content is not: in the same container every table of the Linux database had the same rows as
the Windows original (`EXCEPT ALL` in both directions, equal row counts), and
`validate_suite --suite development` passed on the Linux database. The reference results
therefore match on Linux too: all 40 development reference queries agree with the Windows
results within 1e-9 relative tolerance. The only differences are in the last floating-point
digits, and they also appear between two runs on the same Windows file (parallel summation
order), so they are not a platform effect. Two ways were documented:

1. Download the database from the GitHub Release attachment (step 5) and verify its SHA-256
   in the CI; the commitment is then checked against the published database itself.
2. A separate, clearly labelled verification mode that checks only the case files and the
   oracle against the manifest, and says in its output that the database identity was not
   verified.

Way 1 was chosen. It keeps `verify_commitment` byte-strict and checks everything the manifest
commits to, including the database, and needs no new code path. Way 2 would verify less and
add a mode that could be mistaken for the full check. The cost of way 1: the CI depends on the
Release, so the Release must exist before the CI change is pushed.
