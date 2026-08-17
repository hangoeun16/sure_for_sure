from __future__ import annotations

from pipeline.input_contract import EncounterInput
from pipeline.models import (
    ClaimConfidence,
    ConfidenceLevel,
    ExtractorMetadata,
    PatientClaim,
    RecordEvidence,
    TranscriptSpan,
)
from pipeline.stage_04_link_claims_to_evidence import run
from pipeline.state import PipelineState


def _state(claim_name: str, evidence_name: str) -> PipelineState:
    encounter = EncounterInput(
        id="link-test",
        metadata={},
        patient_context={},
        encounter_fhir={},
        transcript="PT: test",
        note="",
        after_visit_summary="",
        after_visit_summary_provenance={},
    )
    span = TranscriptSpan(turn_index=0, start_char=4, end_char=8, text="test")
    state = PipelineState(encounter=encounter)
    state.claims = [
        PatientClaim(
            claim_id="claim-1",
            medication_name=claim_name,
            supporting_spans=[span],
            confidence=ClaimConfidence(
                level=ConfidenceLevel.NEUTRAL,
                score=0.67,
                rationale="test",
            ),
            first_turn=0,
            last_turn=0,
            extractor=ExtractorMetadata(provider="test", model="test", request_id="test"),
        )
    ]
    state.record_evidence = [
        RecordEvidence(
            evidence_id="evidence-1",
            medication_name=evidence_name,
            resource_type="LongitudinalMedicationLabel",
            source_path="test",
        )
    ]
    return state


def test_generic_name_links_to_rxnorm_formulation() -> None:
    state = run(
        _state(
            "metoprolol",
            "24 HR metoprolol succinate 100 MG Extended Release Oral Tablet",
        )
    )
    assert state.links["claim-1"][0].match_type == "token_compatible"


def test_distinct_medications_do_not_link() -> None:
    state = run(_state("metoprolol", "lisinopril 20 MG Oral Tablet"))
    assert state.links["claim-1"] == []
