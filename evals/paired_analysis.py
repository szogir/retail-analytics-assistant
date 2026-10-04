"""Paired, case-clustered bootstrap analysis of repeated evaluation runs.

Languages and repetitions stay inside their case: resampling individual questions
would exaggerate the independent evidence. This is analysis of this benchmark,
not a population guarantee about arbitrary retail questions.
"""

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from evals.report import CaseResult


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
    args = parser.parse_args()
    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    for key in (
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
    ):
        if before["info"].get(key) != after["info"].get(key):
            raise ValueError(f"Run configurations differ: {key}")
    if before["info"].get("suite") != "holdout":
        raise ValueError("Confirmatory analysis requires the frozen holdout suite")
    if not before["info"].get("holdout_verified") or not before["info"].get(
        "holdout_manifest_hash"
    ):
        raise ValueError("Confirmatory analysis requires a verified public holdout commitment")
    result = paired_bootstrap(
        [CaseResult(**r) for r in before["results"]], [CaseResult(**r) for r in after["results"]]
    )
    if result.cases != before["info"].get("data_case_count", 0):
        raise ValueError(
            "The registered holdout primary analysis requires every recorded data case"
        )
    comparison = f"{after['info']['mode']} minus {before['info']['mode']}"
    confirmatory = (before["info"]["mode"], after["info"]["mode"]) == ("commented", "semantic")
    print(
        json.dumps(
            {"comparison": comparison, "confirmatory": confirmatory, **asdict(result)}, indent=2
        )
    )


if __name__ == "__main__":
    main()
