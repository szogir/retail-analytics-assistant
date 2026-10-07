# Publishing the held-out suite

The held-out suite was sealed during development and is spent after the confirmatory run
([Decision 16](decisions.md#decision-16-confirmatory-holdout-result-2026-10-05)). Publishing
its cases and run files lets anyone check that they are exactly the files that
[`evals/holdout_manifest.json`](../evals/holdout_manifest.json) committed to.

**Status: pending.** The owner performs the steps below. Until the checks in step 4 pass and the
result is committed, the README describes the publication as pending.

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
git grep --cached -n -i -E "codex|claude code|co-authored|generated with|c:\\users|@gmail|api[_-]?key|sk-ant" -- evals/holdout_published evals/results/2026-10-05-holdout
```

No output means nothing was found. The model name `claude-haiku-4-5` in the run files is
expected and is not a finding. Add your own terms (for example an employer or a real brand name)
to the pattern; they are deliberately not listed here. Check also that the staged file list is
what step 1 and 2 produced:

```powershell
git diff --cached --stat -- evals/holdout_published evals/results/2026-10-05-holdout
```

Commit only when both the verification and the scan are clean.

### 5. Publish the database as a release attachment (fallback only)

The generator is seeded and was byte-identical in a fresh clone, so this is a fallback for
platforms where the digest differs. Create the release after the commit has been pushed:

```powershell
gh release create data-v1 data\retail.duckdb --title "Synthetic retail database" `
  --notes "SHA-256: 741bd4c18d8f81433565e2cd96edfe5751283f914753583fdbb82a91188df965"
```

## After publication

- Replace the "pending" notes in the README (Method and database sections) with the links.
- Update the sealed-boundary rules: `CLAUDE.md` section 5 and the read-deny rules in
  `.claude/settings.json` still forbid any access to the held-out suite and must be revised
  before anyone works with the published copy.

## Continuous integration after publication (do later, not now)

After the publication commit, the CI should check the commitment on every push. Run, after
generating the database, `uv run python -m evals.validate_suite --suite holdout --verify
--holdout-dir evals/holdout_published`, and the held-out tests on that folder. Note the current
workflow runs plain `uv run pytest`; use `-m "not live and not review"` there and let the holdout
tests find the published folder.

**Platform caveat.** The CI runs on Linux (`ubuntu-latest`). The byte-identical rebuild of
`data/retail.duckdb` (SHA-256 `741bd4c1...`) was verified on Windows only. If the database hash
differs on the first CI run, there are two ways, to be decided then:

1. Download the database from the GitHub Release attachment (step 5 above) and verify its
   SHA-256 in the CI; the commitment is then checked against the published database itself.
2. A separate, clearly labelled verification mode that checks only the case files and the
   oracle against the manifest (their raw bytes), and says in its output that the database
   identity was not verified.

Neither is implemented. Do not weaken `verify_commitment` for this: it stays byte-strict.
