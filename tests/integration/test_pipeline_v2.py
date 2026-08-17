from __future__ import annotations

import json
from pathlib import Path

from backend.repository import EncounterRepository
from pipeline.models import ActionRoute, EvidenceRelation
from pipeline.providers import StubClaimExtractionProvider
from pipeline.runner import run_pipeline

ROOT = Path(__file__).resolve().parents[2]


def test_public_example_runs_all_ten_stages_with_provenance() -> None:
    repository = EncounterRepository(ROOT / "examples" / "input.example.json")
    encounter, source = repository.get_by_index(0)
    report = run_pipeline(
        encounter,
        StubClaimExtractionProvider(encounter.metadata["claim_extraction"]),
        source=source,
    )
    assert report.summary.claims == 3
    assert report.source is not None and len(report.source.record_sha256) == 64
    assert any(
        item.divergence.relation == EvidenceRelation.SOURCE_CONFLICT for item in report.actions
    )
    assert any(
        item.resolution.resolved and item.route == ActionRoute.CHART_CLEANUP
        for item in report.actions
    )
    assert not any(
        item.resolution.resolved and item.route == ActionRoute.PATIENT_CLARIFICATION
        for item in report.actions
    )
    for claim in report.claims:
        for span in claim.supporting_spans:
            assert encounter.transcript[span.start_char : span.end_char] == span.text


def test_example_output_is_deterministic() -> None:
    repository = EncounterRepository(ROOT / "examples" / "input.example.json")
    encounter, source = repository.get_by_index(0)
    one = run_pipeline(
        encounter,
        StubClaimExtractionProvider(encounter.metadata["claim_extraction"]),
        source=source,
    )
    two = run_pipeline(
        encounter,
        StubClaimExtractionProvider(encounter.metadata["claim_extraction"]),
        source=source,
    )
    assert json.dumps(one.model_dump(mode="json"), sort_keys=True) == json.dumps(
        two.model_dump(mode="json"), sort_keys=True
    )


def test_actions_are_ranked_by_ced_not_route_points() -> None:
    repository = EncounterRepository(ROOT / "examples" / "input.example.json")
    encounter, source = repository.get_by_index(0)
    report = run_pipeline(
        encounter,
        StubClaimExtractionProvider(encounter.metadata["claim_extraction"]),
        source=source,
    )
    ranked = [item for item in report.actions if item.rank is not None]
    assert [item.rank for item in ranked] == list(range(1, len(ranked) + 1))
    assert [item.ced_score for item in ranked] == sorted(
        (item.ced_score for item in ranked), reverse=True
    )
