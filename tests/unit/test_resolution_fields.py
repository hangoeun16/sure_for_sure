from __future__ import annotations

import pytest
from pipeline.ced import DIVERGENCE_SCORE
from pipeline.input_contract import EncounterInput
from pipeline.models import (
    ClaimConfidence,
    ConfidenceLevel,
    DivergenceResult,
    EvidenceRelation,
    ExtractorMetadata,
    PatientClaim,
    RecordEvidence,
    ResolutionResult,
)
from pipeline.stage_01_parse_dialogue import exact_span
from pipeline.stage_01_parse_dialogue import run as parse_dialogue
from pipeline.stage_05_score_divergence import _compare_fields, aggregate_field_relations
from pipeline.stage_07_detect_resolution import run as detect_resolution
from pipeline.state import PipelineState
from pydantic import ValidationError


def _state(transcript: str) -> PipelineState:
    encounter = EncounterInput(
        id="resolution-test",
        metadata={},
        patient_context={},
        encounter_fhir={},
        transcript=transcript,
        note="",
        after_visit_summary="",
        after_visit_summary_provenance={},
    )
    return parse_dialogue(PipelineState(encounter=encounter))


def _claim(
    state: PipelineState,
    claim_id: str,
    turn: int,
    *,
    medication: str = "metoprolol",
    status: str | None = "active",
    dose: float | None = None,
    unit: str | None = None,
    frequency: str | None = None,
    confidence: ConfidenceLevel,
) -> PatientClaim:
    span = exact_span(state, turn_index=turn, quote=state.turns[turn].text)
    return PatientClaim(
        claim_id=claim_id,
        medication_name=medication,
        status=status,
        dose_value=dose,
        dose_unit=unit,
        frequency=frequency,
        supporting_spans=[span],
        confidence=ClaimConfidence(
            level=confidence,
            score={
                ConfidenceLevel.EMPHATIC: 1.0,
                ConfidenceLevel.NEUTRAL: 0.67,
                ConfidenceLevel.HEDGED: 0.33,
                ConfidenceLevel.UNCLEAR: None,
            }[confidence],
            rationale="Test confidence.",
        ),
        first_turn=turn,
        last_turn=turn,
        extractor=ExtractorMetadata(provider="stub", model="test", request_id="test"),
    )


def _record(
    *,
    dose: float | None = 100,
    unit: str | None = "mg",
    frequency: str | None = "daily",
    status: str | None = "active",
) -> RecordEvidence:
    return RecordEvidence(
        evidence_id="rx-1",
        medication_name="metoprolol",
        status=status,
        dose_value=dose,
        dose_unit=unit,
        frequency=frequency,
        resource_type="MedicationRequest",
        resource_id="rx-1",
        source_path="MedicationRequest[rx-1]",
    )


def _divergence(claim: PatientClaim, evidence: list[RecordEvidence]) -> DivergenceResult:
    comparisons = _compare_fields(claim, evidence)
    relation = aggregate_field_relations(comparisons)
    return DivergenceResult(
        claim_id=claim.claim_id,
        relation=relation,
        divergence_score=DIVERGENCE_SCORE[relation],
        disputed_fields=sorted(
            item.field for item in comparisons if item.relation != EvidenceRelation.SUPPORT
        ),
        field_comparisons=comparisons,
        supporting_evidence_ids=sorted(
            {
                evidence_id
                for item in comparisons
                if item.relation == EvidenceRelation.SUPPORT
                for evidence_id in item.evidence_ids
            }
        ),
        conflicting_evidence_ids=sorted(
            {
                evidence_id
                for item in comparisons
                if item.relation
                in {EvidenceRelation.CONTRADICT, EvidenceRelation.SOURCE_CONFLICT}
                for evidence_id in item.evidence_ids
            }
        ),
        rationale="Fixture discrepancy.",
    )


def _resolve(
    state: PipelineState,
    original: PatientClaim,
    later: list[PatientClaim],
    evidence: list[RecordEvidence] | None = None,
) -> ResolutionResult:
    chart = evidence or [_record()]
    state.claims = [original, *later]
    state.divergences = {claim.claim_id: _divergence(claim, chart) for claim in state.claims}
    return detect_resolution(state).resolutions[original.claim_id]


def test_later_status_only_claim_does_not_resolve_dose_discrepancy() -> None:
    state = _state("PT: I think I take metoprolol 50 mg.\nPT: I definitely still take metoprolol.")
    original = _claim(state, "earlier", 0, dose=50, unit="mg", confidence=ConfidenceLevel.HEDGED)
    later = _claim(state, "later", 1, confidence=ConfidenceLevel.EMPHATIC)
    result = _resolve(state, original, [later])
    assert result.resolved is False
    assert result.unresolved_fields == ["dose_value"]


def test_later_explicit_corrected_dose_resolves_dose_discrepancy() -> None:
    state = _state(
        "PT: I think I take metoprolol 50 mg.\nPT: I definitely take metoprolol 100 mg now."
    )
    original = _claim(state, "earlier", 0, dose=50, unit="mg", confidence=ConfidenceLevel.HEDGED)
    later = _claim(state, "later", 1, dose=100, unit="mg", confidence=ConfidenceLevel.EMPHATIC)
    result = _resolve(state, original, [later])
    assert result.resolved is True
    assert result.resolved_fields == ["dose_value"]
    assert result.unresolved_fields == []


def test_later_claim_omitting_frequency_does_not_resolve_frequency_discrepancy() -> None:
    state = _state(
        "PT: I think I take metoprolol twice daily.\nPT: I definitely take metoprolol 100 mg."
    )
    original = _claim(
        state,
        "earlier",
        0,
        frequency="twice daily",
        confidence=ConfidenceLevel.HEDGED,
    )
    later = _claim(state, "later", 1, dose=100, unit="mg", confidence=ConfidenceLevel.EMPHATIC)
    assert _resolve(state, original, [later]).resolved is False


def test_later_status_statement_resolves_status_discrepancy() -> None:
    state = _state("PT: I think I stopped metoprolol.\nPT: I definitely still take metoprolol.")
    original = _claim(state, "earlier", 0, status="stopped", confidence=ConfidenceLevel.HEDGED)
    later = _claim(state, "later", 1, status="active", confidence=ConfidenceLevel.EMPHATIC)
    result = _resolve(state, original, [later], [_record(dose=None, unit=None, frequency=None)])
    assert result.resolved is True
    assert result.resolved_fields == ["status"]


def test_all_disputed_fields_must_be_addressed() -> None:
    state = _state(
        "PT: I think I take metoprolol 50 mg twice daily.\nPT: I definitely take metoprolol 100 mg."
    )
    original = _claim(
        state,
        "earlier",
        0,
        dose=50,
        unit="mg",
        frequency="twice daily",
        confidence=ConfidenceLevel.HEDGED,
    )
    later = _claim(state, "later", 1, dose=100, unit="mg", confidence=ConfidenceLevel.EMPHATIC)
    result = _resolve(state, original, [later])
    assert result.resolved is False
    assert result.resolved_fields == ["dose_value"]
    assert result.unresolved_fields == ["frequency"]


def test_split_later_claims_do_not_union_fields_under_single_claim_model() -> None:
    state = _state(
        "PT: I think I take metoprolol 50 mg twice daily.\n"
        "PT: I definitely take metoprolol 100 mg.\n"
        "PT: I definitely take metoprolol daily."
    )
    original = _claim(
        state,
        "earlier",
        0,
        dose=50,
        unit="mg",
        frequency="twice daily",
        confidence=ConfidenceLevel.HEDGED,
    )
    dose_only = _claim(
        state,
        "later-dose",
        1,
        dose=100,
        unit="mg",
        confidence=ConfidenceLevel.EMPHATIC,
    )
    frequency_only = _claim(
        state,
        "later-frequency",
        2,
        frequency="daily",
        confidence=ConfidenceLevel.EMPHATIC,
    )
    result = _resolve(state, original, [dose_only, frequency_only])
    assert result.resolved is False
    assert result.resolved_fields == ["dose_value"]
    assert result.unresolved_fields == ["frequency"]
    assert result.resolving_claim_id is None
    assert not result.rationale.rstrip().endswith("still unresolved:")


def test_repeating_conflicting_value_does_not_resolve_mentioned_field() -> None:
    state = _state(
        "PT: I think I take metoprolol 50 mg.\nPT: I definitely take metoprolol 50 mg."
    )
    original = _claim(state, "earlier", 0, dose=50, unit="mg", confidence=ConfidenceLevel.HEDGED)
    repeated = _claim(
        state,
        "later",
        1,
        dose=50,
        unit="mg",
        confidence=ConfidenceLevel.EMPHATIC,
    )
    result = _resolve(state, original, [repeated])
    assert result.resolved is False
    assert result.resolved_fields == []
    assert result.unresolved_fields == ["dose_value"]


def test_no_later_candidate_leaves_every_disputed_field_unresolved() -> None:
    state = _state("PT: I think I take metoprolol 50 mg twice daily.")
    original = _claim(
        state,
        "earlier",
        0,
        dose=50,
        unit="mg",
        frequency="twice daily",
        confidence=ConfidenceLevel.HEDGED,
    )
    result = _resolve(state, original, [])
    assert result.resolved is False
    assert result.resolved_fields == []
    assert result.unresolved_fields == ["dose_value", "frequency"]


def test_unrelated_later_medication_does_not_resolve() -> None:
    state = _state("PT: I think I take metoprolol 50 mg.\nPT: I definitely take lisinopril 10 mg.")
    original = _claim(state, "earlier", 0, dose=50, unit="mg", confidence=ConfidenceLevel.HEDGED)
    later = _claim(
        state,
        "later",
        1,
        medication="lisinopril",
        dose=10,
        unit="mg",
        confidence=ConfidenceLevel.EMPHATIC,
    )
    result = _resolve(state, original, [later])
    assert result.resolved is False
    assert result.resolved_fields == []
    assert result.unresolved_fields == ["dose_value"]


@pytest.mark.parametrize(
    ("resolved", "resolved_fields", "unresolved_fields"),
    [
        (True, [], ["dose_value"]),
        (False, ["dose_value"], []),
        (False, ["dose_value"], ["dose_value"]),
    ],
)
def test_resolution_model_rejects_contradictory_field_state(
    resolved: bool,
    resolved_fields: list[str],
    unresolved_fields: list[str],
) -> None:
    with pytest.raises(ValidationError):
        ResolutionResult(
            claim_id="invalid",
            resolved=resolved,
            disputed_fields=["dose_value"],
            resolved_fields=resolved_fields,
            unresolved_fields=unresolved_fields,
            rationale="Invalid test state.",
        )
