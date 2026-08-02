"""Static governance checks for the versioned retrieval regression corpus."""

import json
from pathlib import Path
from typing import Any, cast

CORPUS = Path(__file__).parent / "ai_evaluation/retrieval_regression_v1.json"


def test_retrieval_regression_corpus_is_versioned_bounded_and_complete() -> None:
    payload = cast("dict[str, Any]", json.loads(CORPUS.read_text(encoding="utf-8")))
    assert payload["dataset_version"] == "retrieval-regression-v1"
    thresholds = payload["quality_thresholds"]
    assert thresholds == {
        "minimum_top_1_accuracy": 1.0,
        "minimum_mean_reciprocal_rank": 1.0,
        "maximum_warm_p95_latency_ms": 750,
    }
    cases = payload["cases"]
    assert 5 <= len(cases) <= 25
    assert len({case["case_id"] for case in cases}) == len(cases)
    required = {
        "fusion-apps-26c-ap-error",
        "fdi-26r2-release-family",
        "analyst-source-separation",
        "employee-cannot-see-analyst-source",
        "restricted-and-cross-tenant-canary-denial",
        "bounded-zero-result",
    }
    assert {case["case_id"] for case in cases} == required
    assert all(1 <= len(case["query"]) <= 500 for case in cases)
    assert all(case["forbidden_external_keys"] for case in cases)
