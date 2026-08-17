from __future__ import annotations

import pytest
from pipeline.input_contract import EncounterInput
from pipeline.models import (
    ClaimConfidence,
    ConfidenceLevel,
    DivergenceResult,
    EvidenceRelation,
    ExtractorMetadata,
    FieldComparison,
    PatientClaim,
    ResolutionResult,
    TranscriptSpan,
)
from pipeline.stage_06_compute_ced import run as compute_ced
from pipeline.stage_08_route_actions import run as route_actions
from pipeline.state import PipelineState


def _encounter() -> EncounterInput:
    return EncounterInput(
        id="ced-test",
        metadata={},
        patient_context={},
        encounter_fhir={},
        transcript="PT: I take the medicine",
        note="",
        after_visit_summary="",
        after_visit_summary_provenance={},
    )


def _claim() -> PatientClaim:
    span = TranscriptSpan(turn_index=0, start_char=4, end_char=20, text="I take the medicine")
    return PatientClaim(
        claim_id="claim-ced",
        medication_name="metoprolol",
        dose_value=50,
        dose_unit="mg",
        supporting_spans=[span],
        confidence=ClaimConfidence(
            level=ConfidenceLevel.NEUTRAL,
            score=0.67,
            rationale="Ordinary assertion.",
        ),
        first_turn=0,
        last_turn=0,
        extractor=ExtractorMetadata(provider="stub", model="test", request_id="test"),
    )


def _state(relation: EvidenceRelation, *, resolved: bool = False) -> PipelineState:
    claim = _claim()
    state = PipelineState(encounter=_encounter())
    state.claims = [claim]
    state.divergences[claim.claim_id] = DivergenceResult(
        claim_id=claim.claim_id,
        relation=relation,
        divergence_score={
            EvidenceRelation.SUPPORT: 0.0,
            EvidenceRelation.SILENT: 0.5,
            EvidenceRelation.CONTRADICT: 1.0,
            EvidenceRelation.SOURCE_CONFLICT: 0.75,
        }[relation],
        disputed_fields=[] if relation == EvidenceRelation.SUPPORT else ["dose_value"],
        field_comparisons=[
            FieldComparison(
                field="dose_value",
                relation=relation,
                claim_value=50,
                record_values=[100] if relation != EvidenceRelation.SILENT else [],
                evidence_ids=["evidence-1"] if relation != EvidenceRelation.SILENT else [],
                rationale="Test comparison.",
            )
        ],
        supporting_evidence_ids=[],
        conflicting_evidence_ids=["evidence-1"]
        if relation in {EvidenceRelation.CONTRADICT, EvidenceRelation.SOURCE_CONFLICT}
        else [],
        rationale="Test divergence.",
    )
    state.resolutions[claim.claim_id] = ResolutionResult(
        claim_id=claim.claim_id,
        resolved=resolved,
        resolution_type="patient_clarification" if resolved else None,
        disputed_fields=[] if relation == EvidenceRelation.SUPPORT else ["dose_value"],
        resolved_fields=["dose_value"] if resolved else [],
        unresolved_fields=[]
        if resolved or relation == EvidenceRelation.SUPPORT
        else ["dose_value"],
        rationale="All disputed fields were established later."
        if resolved
        else "Dose remains unresolved.",
    )
    return compute_ced(state)


@pytest.mark.parametrize(
    ("relation", "expected"),
    [
        (EvidenceRelation.SUPPORT, 0.0),
        (EvidenceRelation.SILENT, 0.335),
        (EvidenceRelation.CONTRADICT, 0.67),
        (EvidenceRelation.SOURCE_CONFLICT, 0.5025),
    ],
)
def test_ced_inputs_are_explicit_for_each_relation(
    relation: EvidenceRelation, expected: float
) -> None:
    state = _state(relation)
    result = state.ced_results["claim-ced"]
    assert result.confidence_score == 0.67
    assert result.divergence_score == state.divergences["claim-ced"].divergence_score
    assert result.ced_score == expected


def test_resolution_changes_route_without_rewriting_ced() -> None:
    unresolved = route_actions(_state(EvidenceRelation.CONTRADICT, resolved=False))
    resolved = route_actions(_state(EvidenceRelation.CONTRADICT, resolved=True))
    assert unresolved.ced_results["claim-ced"].ced_score == 0.67
    assert resolved.ced_results["claim-ced"].ced_score == 0.67
    assert unresolved.actions[0].route.value == "patient_clarification"
    assert resolved.actions[0].route.value == "no_action"
