"""Tests for the semantic ablation study (Decision 23).

The key promise: the "full" variant is byte-for-byte the frozen v3 prompt, so every earlier
measurement stays valid, and an ablation can only ever be compared diagnostically.
Everything runs offline; the published holdout copy is read only by the failure-analysis
test, as regression data.
"""

import datetime as dt
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest
from typer.testing import CliRunner

from evals import run_eval
from evals.ablation_summary import render_table, summarize
from evals.failure_analysis import analyze_run_file
from evals.paired_analysis import main as paired_main
from evals.report import CaseResult, RunInfo, render_report
from evals.suites import PROJECT_ROOT, PUBLISHED_HOLDOUT
from retail_assistant.llm.fake import FakeLLMClient
from retail_assistant.llm.profiles import load_profile
from retail_assistant.llm.schemas import SqlAnswer
from retail_assistant.pipeline import ask
from retail_assistant.semantic.context import ABLATIONS, build_system_prompt

PROMPTS_DIR = PROJECT_ROOT / "config" / "prompts"
SEMANTIC_DIR = PROJECT_ROOT / "semantic"
PROFILE = load_profile(PROJECT_ROOT / "config" / "models.yaml", "claude_small")

# SHA-256 of the system prompts recorded in the run files before the ablation study
# (Decision 15 for semantic v3; the naive and commented values from the day-4 runs). They are
# public digests, not secrets; the pragma tells the secret scanner so.
FROZEN_PROMPT_HASHES = {
    # pragma: allowlist nextline secret
    "naive": "21c6c86f8dd2a06940681d699255ae2a21299d1fb08fef119225dfcbb8bbf217",
    # pragma: allowlist nextline secret
    "commented": "b4f795af5e9155f1a622684e37e2a4f1f62dfa5070d23c4f50cdce4e2c51be95",
    # pragma: allowlist nextline secret
    "semantic": "e3e91b83212118e600cd8b2bf8a754166eeb5c27ff574c8317c12acbbaa6cc25",
}
# pragma: allowlist nextline secret
FROZEN_SCORING_HASH = "1056bb8f5c5fd44683dddbb78260560811c205ce3202117e20d70db4c8d69349"
# A wide terminal, so the usage-error box does not wrap the message the tests look for.
WIDE = {"COLUMNS": "300"}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# --- the prompt -------------------------------------------------------------------------------


def test_full_variant_is_the_frozen_v3_prompt(full_db_path: Path) -> None:
    # Hashing the rendered prompt, not the raw YAML files: the files differ in an LF checkout
    # (Decision 21), the prompt built from them does not.
    default = build_system_prompt("semantic", full_db_path, PROMPTS_DIR, SEMANTIC_DIR)
    explicit = build_system_prompt("semantic", full_db_path, PROMPTS_DIR, SEMANTIC_DIR, "full")
    assert sha256(default) == sha256(explicit) == FROZEN_PROMPT_HASHES["semantic"]


@pytest.mark.parametrize("mode", ["naive", "commented"])
def test_baseline_prompts_are_unchanged(full_db_path: Path, mode: str) -> None:
    prompt = build_system_prompt(mode, full_db_path, PROMPTS_DIR)  # type: ignore[arg-type]
    assert sha256(prompt) == FROZEN_PROMPT_HASHES[mode]


def test_scoring_hash_is_unchanged() -> None:
    assert run_eval.scoring_hash() == FROZEN_SCORING_HASH


@pytest.mark.parametrize(
    ("ablation", "rules", "examples"),
    [
        ("full", True, True),
        ("no_examples", True, False),
        ("no_rules", False, True),
        ("metrics_joins", False, False),
    ],
)
def test_each_variant_leaves_out_exactly_its_sections(
    full_db_path: Path, ablation: str, rules: bool, examples: bool
) -> None:
    prompt = build_system_prompt(
        "semantic",
        full_db_path,
        PROMPTS_DIR,
        SEMANTIC_DIR,
        ablation,  # type: ignore[arg-type]
    )
    assert ("### Rules" in prompt) is rules
    assert ("### Verified examples" in prompt) is examples
    # Metrics and join paths are the core that every variant keeps.
    assert "### Metrics" in prompt and "### Join paths" in prompt
    assert "{semantic}" not in prompt


def test_variants_produce_four_different_prompts(full_db_path: Path) -> None:
    prompts = {
        build_system_prompt("semantic", full_db_path, PROMPTS_DIR, SEMANTIC_DIR, name)
        for name in ABLATIONS
    }
    assert len(prompts) == 4


def test_an_ablation_outside_the_semantic_mode_is_refused(full_db_path: Path) -> None:
    with pytest.raises(ValueError, match="only defined for the semantic mode"):
        build_system_prompt("commented", full_db_path, PROMPTS_DIR, None, "no_rules")


def test_the_pipeline_sends_the_ablated_prompt(tiny_db: Path) -> None:
    answer = SqlAnswer.model_validate(
        {"language": "en", "intent": "metric_query", "approach": "count", "sql": "SELECT 1"}
    )
    fake = FakeLLMClient(responses=[answer])
    ask(
        "How many stores?",
        "carla",
        "en",
        "semantic",
        llm=fake,
        profile=PROFILE,
        db_path=tiny_db,
        prompts_dir=PROMPTS_DIR,
        as_of=dt.date(2026, 10, 10),
        semantic_dir=SEMANTIC_DIR,
        validate=False,
        ablation="metrics_joins",
    )
    assert "### Metrics" in fake.calls[0].system
    assert "### Rules" not in fake.calls[0].system


# --- the eval runner's guards ------------------------------------------------------------------


def test_cli_refuses_an_ablation_outside_the_semantic_mode() -> None:
    result = CliRunner(env=WIDE).invoke(
        run_eval.app, ["--mode", "commented", "--ablation", "no_rules"]
    )
    assert result.exit_code == 2
    assert "only defined for --mode semantic" in result.output


def test_cli_refuses_an_unknown_ablation() -> None:
    result = CliRunner(env=WIDE).invoke(
        run_eval.app, ["--mode", "semantic", "--ablation", "no_metrics"]
    )
    assert result.exit_code == 2
    assert "ablation must be one of" in result.output


def test_holdout_ablation_needs_the_published_folder_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The guard must fire before HOLDOUT_DIR is ever consulted.
    monkeypatch.setenv("HOLDOUT_DIR", str(tmp_path / "must-not-be-read"))
    base = ["--suite", "holdout", "--mode", "semantic", "--ablation", "no_rules"]
    for extra in ([], ["--holdout-dir", str(tmp_path)]):
        result = CliRunner(env=WIDE).invoke(run_eval.app, [*base, *extra])
        assert result.exit_code == 2
        assert "needs --holdout-dir evals/holdout_published" in result.output


def test_the_holdout_still_refuses_backend_options_with_an_ablation() -> None:
    published = str(PROJECT_ROOT / PUBLISHED_HOLDOUT)
    result = CliRunner(env=WIDE).invoke(
        run_eval.app,
        ["--suite", "holdout", "--holdout-dir", published, "--mode", "semantic"]
        + ["--ablation", "no_rules", "--validator"],
    )
    assert result.exit_code == 2
    assert "not run with new options" in result.output


def test_holdout_regression_output_is_outside_the_published_folder() -> None:
    published = (PROJECT_ROOT / PUBLISHED_HOLDOUT).resolve()
    assert not run_eval.HOLDOUT_REGRESSION_DIR.resolve().is_relative_to(published)


# --- run info, report and summary --------------------------------------------------------------


def info(**changes: object) -> RunInfo:
    values: dict[str, object] = {
        "mode": "semantic",
        "profile": "claude_small",
        "model": "m",
        "prompt_version": "sql_semantic_v1",
        "price_date": "2026-10-04",
        "run_date": "2026-10-10",
        "max_tokens": 1024,
    }
    values.update(changes)
    return RunInfo(**values)  # type: ignore[arg-type]


def row(case_id: str, kind: str, status: str, primary: bool, repeat: int = 1) -> CaseResult:
    return CaseResult(
        case_id,
        "en",
        "c",
        kind,
        status,
        primary,
        primary,
        1.0,
        0.01,
        primary=primary,
        repeat=repeat,
    )


def test_old_run_info_without_the_key_means_full() -> None:
    old = asdict(info())
    del old["ablation"]
    assert RunInfo(**old).ablation == "full"


def test_report_shows_the_variant_and_the_clarification_behaviour() -> None:
    results = [
        row("1", "result", "answered", True),
        row("2", "result", "clarification", False),
        row("3", "clarification", "clarification", True),
        row("4", "clarification", "answered", False),
    ]
    text = render_report(info(ablation="no_rules"), results, None, 4)
    assert "- Semantic ablation: `no_rules`" in text
    assert "Asked back on clarification cases: **50% (1/2)**" in text
    assert "Asked back needlessly on data cases: **50% (1/2)**" in text


def test_summary_counts_per_variant() -> None:
    results = [
        row("1", "result", "answered", True, repeat=1),
        row("1", "result", "clarification", False, repeat=2),
        row("2", "clarification", "clarification", True, repeat=1),
        row("2", "clarification", "answered", False, repeat=2),
    ]
    summary = summarize({"suite": "holdout", "ablation": "no_examples"}, results)
    assert summary.primary == (1, 2)
    assert summary.per_repeat == [1.0, 0.0]
    assert summary.asked == (1, 2)
    assert summary.needless == (1, 2)
    assert summarize({"suite": "development"}, results).ablation == "full"
    table = render_table([summary])
    assert "| holdout | no_examples | 50.0% (1/2) | 100.0 / 0.0 |" in table


# --- paired analysis ---------------------------------------------------------------------------


def paired_rows(correct: bool) -> list[dict[str, object]]:
    return [
        asdict(
            CaseResult(
                case_id,
                lang,
                "c",
                "result",
                "answered",
                correct,
                correct,
                1.0,
                0.0,
                primary=correct,
                repeat=repeat,
            )
        )
        for case_id in ("a", "b")
        for lang in ("en", "hu")
        for repeat in (1, 2, 3)
    ]


HOLDOUT_INFO: dict[str, object] = {
    "suite": "holdout",
    "mode": "semantic",
    "holdout_verified": True,
    "holdout_manifest_hash": "manifest",
    "data_case_count": 2,
    "config_hash": "c",
}


def run_paired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    before: dict[str, object],
    after: dict[str, object],
    diagnostic: bool,
) -> None:
    paths = []
    for name, extra, correct in (("before", before, True), ("after", after, False)):
        path = tmp_path / f"{name}.json"
        document = {"info": {**HOLDOUT_INFO, **extra}, "results": paired_rows(correct)}
        path.write_text(json.dumps(document), encoding="utf-8")
        paths.append(str(path))
    flags = ["--diagnostic"] if diagnostic else []
    monkeypatch.setattr("sys.argv", ["paired_analysis", *paths, *flags])
    paired_main()


def test_holdout_ablation_pair_is_diagnostic_regression_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The "before" file has no ablation key, like every run file from before the study.
    run_paired(tmp_path, monkeypatch, {}, {"ablation": "no_rules"}, diagnostic=True)
    output = json.loads(capsys.readouterr().out)
    assert output["confirmatory"] is False
    assert output["label"].startswith("DIAGNOSTIC (published holdout, regression data)")
    assert output["ablation_differs"] == ["full", "no_rules"]
    assert output["comparison"] == "semantic[no_rules] minus semantic[full]"
    assert "meets_success_rule" not in output
    assert output["difference"] == -1.0


def test_holdout_ablation_pair_without_diagnostic_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="differ: ablation"):
        run_paired(tmp_path, monkeypatch, {}, {"ablation": "no_rules"}, diagnostic=False)


def test_holdout_same_variant_with_diagnostic_still_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="only for runs of the development suite"):
        run_paired(tmp_path, monkeypatch, {}, {}, diagnostic=True)


def test_ablation_does_not_excuse_another_identity_difference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="differ: config_hash"):
        run_paired(
            tmp_path,
            monkeypatch,
            {},
            {"ablation": "no_rules", "config_hash": "other"},
            diagnostic=True,
        )


def test_holdout_ablation_pair_with_a_backend_difference_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="differ: validator"):
        run_paired(
            tmp_path, monkeypatch, {}, {"ablation": "no_rules", "validator": True}, diagnostic=True
        )


def test_holdout_ablation_pair_must_be_two_semantic_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="only for runs of the development suite"):
        run_paired(
            tmp_path, monkeypatch, {"mode": "commented"}, {"ablation": "no_rules"}, diagnostic=True
        )


# --- failure analysis on the published holdout -------------------------------------------------


def write_run(path: Path, suite: str) -> None:
    document = {"info": {"suite": suite, "mode": "semantic", "repetitions": 1}, "results": []}
    path.write_text(json.dumps(document), encoding="utf-8")


def test_failure_analysis_reads_holdout_runs_only_against_the_published_copy(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run.json"
    write_run(run, "holdout")
    published = PROJECT_ROOT / PUBLISHED_HOLDOUT
    assert analyze_run_file(run, golden_dir=published).failed_questions == 0
    with pytest.raises(ValueError, match="only analysed against evals/holdout_published"):
        analyze_run_file(run, golden_dir=tmp_path)
    write_run(run, "development")
    with pytest.raises(ValueError, match="needs the development references"):
        analyze_run_file(run, golden_dir=published)


def test_development_ablation_pair_with_a_backend_difference_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    development = {"suite": "development", "holdout_verified": False, "holdout_manifest_hash": ""}
    with pytest.raises(ValueError, match="differ: validator"):
        run_paired(
            tmp_path,
            monkeypatch,
            development,
            {**development, "ablation": "no_rules", "validator": True},
            diagnostic=True,
        )


def test_development_ablation_pair_is_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    development = {"suite": "development", "holdout_verified": False, "holdout_manifest_hash": ""}
    run_paired(tmp_path, monkeypatch, development, {**development, "ablation": "no_examples"}, True)
    output = json.loads(capsys.readouterr().out)
    assert output["label"].startswith("DIAGNOSTIC (development suite)")
    assert output["ablation_differs"] == ["full", "no_examples"]


class ReachedTheModel(Exception):
    """Raised by the patched model factory: every check before the first model call passed."""


@pytest.mark.parametrize("ablation", ["full", "no_rules"])
def test_the_owner_command_on_the_published_holdout_passes_every_guard(
    monkeypatch: pytest.MonkeyPatch, ablation: str
) -> None:
    # The exact command shape of the holdout regression runs, stopped just before the first
    # model call. It proves the guards, the commitment check of the published folder and the
    # settings all pass, without HOLDOUT_DIR and without spending anything.
    monkeypatch.delenv("HOLDOUT_DIR", raising=False)

    def stop(*args: object) -> None:
        raise ReachedTheModel

    monkeypatch.setattr(run_eval, "create_llm", stop)
    published = "evals/holdout_published"
    result = CliRunner(env=WIDE).invoke(
        run_eval.app,
        ["--suite", "holdout", "--holdout-dir", published, "--mode", "semantic"]
        + ["--profile", "claude_small", "--repetitions", "3", "--ablation", ablation],
    )
    assert isinstance(result.exception, ReachedTheModel), result.output
