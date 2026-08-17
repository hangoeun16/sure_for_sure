from pathlib import Path

from backend.repository import EncounterRepository
from pipeline.models import ActionRoute, EvidenceRelation
from pipeline.providers import StubClaimExtractionProvider
from pipeline.runner import run_pipeline


def _report():
    path = Path(__file__).resolve().parents[2] / "examples" / "input.example.json"
    repository = EncounterRepository(path)
    encounter, source = repository.get_by_index(0)
    return run_pipeline(
        encounter,
        StubClaimExtractionProvider(encounter.metadata["claim_extraction"]),
        source=source,
    )


def test_source_conflict_is_not_silently_adjudicated() -> None:
    assert (
        _report().divergences[next(iter(_report().divergences))].relation
        == EvidenceRelation.SOURCE_CONFLICT
    )


def test_resolved_question_can_leave_chart_cleanup() -> None:
    assert any(
        action.resolution.resolved and action.route == ActionRoute.CHART_CLEANUP
        for action in _report().actions
    )


def test_resolved_question_is_not_reasked() -> None:
    assert not any(
        action.resolution.resolved and action.route == ActionRoute.PATIENT_CLARIFICATION
        for action in _report().actions
    )
