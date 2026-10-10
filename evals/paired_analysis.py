"""Paired, case-clustered bootstrap analysis of repeated evaluation runs.

Languages and repetitions stay inside their case: resampling individual questions
would exaggerate the independent evidence. This is analysis of this benchmark,
not a population guarantee about arbitrary retail questions.

Usage:
    uv run python -m evals.paired_analysis before.json after.json
    uv run python -m evals.paired_analysis before.json after.json --diagnostic
"""

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from evals.report import CaseResult

# Run settings that must be identical in every comparison, confirmatory or diagnostic.
IDENTITY_KEYS = (
    "suite",
    "case_hash",
    "database_hash",
    "model",
    "max_tokens",
    "scoring_version",
    "repetitions",
    "config_hash",
    "scoring_hash",
    "schema_hash",
    "data_case_count",
    "holdout_manifest_hash",
    "holdout_verified",
)
# Backend settings added on day 5, with the value that older run files implicitly had.
BACKEND_DEFAULTS: dict[str, object] = {"validator": False, "retry": False, "user": ""}
# The semantic ablation variant (Decision 23); run files from before the study were "full".
ABLATION_DEFAULT = "full"


def differing_backend_settings(before: dict[str, object], after: dict[str, object]) -> list[str]:
    """Names of the backend settings (validator, retry, user) that differ between two runs."""
    return [
        key
        for key, default in BACKEND_DEFAULTS.items()
        if before.get(key, default) != after.get(key, default)
    ]


@dataclass(frozen=True)
class PairedEstimate:
    """Mean accuracy difference and a percentile interval in units of 0–1."""

    cases: int
    difference: float
    lower: float
    upper: float
    bootstrap_samples: int
    seed: int
    meets_success_rule: bool


def paired_bootstrap(
    before: list[CaseResult], after: list[CaseResult], *, samples: int = 10000, seed: int = 42
) -> PairedEstimate:
    """Resample case-level differences, retaining EN/HU and three repeated runs.

    Args:
        before: All outcomes of the reference mode, including failures.
        after: All outcomes of the candidate mode on exactly the same cases.
        samples: Number of bootstrap samples.
        seed: Fixed seed for reproducibility.

    Returns:
        Point estimate, two-sided 95% interval and the preregistered 10-point gate.

    Raises:
        ValueError: For duplicates, missing pairs, or incomplete language/repeat clusters.
    """
    if samples < 1:
        raise ValueError("samples must be positive")
    left = {(r.case_id, r.lang, r.repeat): r for r in before}
    right = {(r.case_id, r.lang, r.repeat): r for r in after}
    if len(left) != len(before) or len(right) != len(after) or left.keys() != right.keys():
        raise ValueError("Runs must have identical, unique case/language/repetition keys")
    for key in left:
        if left[key].expected_kind != right[key].expected_kind:
            raise ValueError("Expected kinds differ between modes")
    ids = sorted({r.case_id for r in before if r.expected_kind in ("result", "result_scoped")})
    if not ids:
        raise ValueError("No result cases")
    differences = []
    expected_cluster = {(lang, repeat) for lang in ("en", "hu") for repeat in (1, 2, 3)}
    for case_id in ids:
        keys = [key for key in left if key[0] == case_id]
        if {(key[1], key[2]) for key in keys} != expected_cluster:
            raise ValueError("Every result case needs both languages and all three repetitions")
        differences.append(
            sum(int(right[key].primary) - int(left[key].primary) for key in keys) / len(keys)
        )
    values = np.array(differences, dtype=float)
    rng = np.random.default_rng(seed)
    means = rng.choice(values, size=(samples, len(values)), replace=True).mean(axis=1)
    quantiles = np.quantile(means, [0.025, 0.975])
    # Convert to plain floats BEFORE comparing: a comparison on a NumPy scalar yields
    # `np.bool_`, which `json.dumps` rejects. Design note: the alternative, a custom
    # JSON encoder, would hide the problem instead of keeping the result type plain.
    lower = float(quantiles[0])
    upper = float(quantiles[1])
    difference = float(values.mean())
    return PairedEstimate(
        len(ids),
        difference,
        lower,
        upper,
        samples,
        seed,
        difference >= 0.10 and lower > 0,
    )


def main() -> None:
    """Compare two complete three-repetition run artifacts without changing them."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="allow two runs of the DEVELOPMENT suite, or two ablation variants on the "
        "published holdout; the output is labelled diagnostic and is never a confirmatory result",
    )
    args = parser.parse_args()
    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    for key in IDENTITY_KEYS:
        if before["info"].get(key) != after["info"].get(key):
            raise ValueError(f"Run configurations differ: {key}")
    # Design note: the confirmatory rules stay exactly as preregistered. The diagnostic path is
    # a separate, explicitly opt-in branch for the development suite whose output says so;
    # the alternative, loosening the holdout checks, could turn a development number into
    # something that looks confirmatory.
    suite = before["info"].get("suite")
    ablations = [
        before["info"].get("ablation", ABLATION_DEFAULT),
        after["info"].get("ablation", ABLATION_DEFAULT),
    ]
    ablation_differs = ablations[0] != ablations[1]
    # Decision 23: the spent holdout is regression data, so two ablation variants on it may be
    # compared diagnostically. Only the ablation may differ there; two runs of the same variant
    # on the holdout keep the confirmatory rules below, and so does a mode comparison.
    both_semantic = before["info"].get("mode") == after["info"].get("mode") == "semantic"
    holdout_ablation = suite == "holdout" and ablation_differs and both_semantic
    diagnostic = args.diagnostic and (suite == "development" or holdout_ablation)
    if args.diagnostic and not diagnostic:
        raise ValueError(
            "--diagnostic is only for runs of the development suite, "
            "or for two ablation variants on the published holdout"
        )
    if ablation_differs and not diagnostic:
        raise ValueError("Run configurations differ: ablation")
    # Backend settings (day 5) may differ only in a diagnostic comparison, for example "semantic
    # without validator" versus "semantic with validator". Every other identity key above stays
    # mandatory. Older run files have no such keys; they mean "off / off / each case's user".
    # An ablation comparison changes exactly one thing, so no backend difference is allowed in it.
    differing = differing_backend_settings(before["info"], after["info"])
    if differing and (not diagnostic or ablation_differs):
        raise ValueError(f"Run configurations differ: {', '.join(differing)}")
    verified = bool(
        before["info"].get("holdout_verified") and before["info"].get("holdout_manifest_hash")
    )
    if holdout_ablation and not verified:
        raise ValueError("A holdout ablation comparison requires the verified published holdout")
    if not diagnostic:
        if before["info"].get("suite") != "holdout":
            raise ValueError("Confirmatory analysis requires the frozen holdout suite")
        if not verified:
            raise ValueError("Confirmatory analysis requires a verified public holdout commitment")
    result = paired_bootstrap(
        [CaseResult(**r) for r in before["results"]], [CaseResult(**r) for r in after["results"]]
    )
    if result.cases != before["info"].get("data_case_count", 0):
        raise ValueError(
            "The registered holdout primary analysis requires every recorded data case"
        )
    comparison = f"{after['info']['mode']} minus {before['info']['mode']}"
    if ablation_differs:
        after_label = f"{after['info']['mode']}[{ablations[1]}]"
        before_label = f"{before['info']['mode']}[{ablations[0]}]"
        comparison = f"{after_label} minus {before_label}"
    confirmatory = (before["info"]["mode"], after["info"]["mode"]) == (
        "commented",
        "semantic",
    ) and not diagnostic
    estimate = asdict(result)
    label: dict[str, object] = {}
    if ablation_differs:
        label["ablation_differs"] = ablations
    if differing:
        label["backend_settings_differ"] = {
            key: [
                before["info"].get(key, BACKEND_DEFAULTS[key]),
                after["info"].get(key, BACKEND_DEFAULTS[key]),
            ]
            for key in differing
        }
    if diagnostic:
        # The success rule belongs to the holdout; showing it for development data would
        # invite reading a diagnostic number as a claim.
        del estimate["meets_success_rule"]
        label["label"] = (
            "DIAGNOSTIC (published holdout, regression data): not confirmatory, "
            "no success-rule verdict"
            if holdout_ablation
            else "DIAGNOSTIC (development suite): not confirmatory, no success-rule verdict"
        )
    print(
        json.dumps(
            {"comparison": comparison, "confirmatory": confirmatory, **label, **estimate},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
