from __future__ import annotations

from pipeline.models import (
    ClaimConfidence,
    ConfidenceLevel,
    EvidenceRelation,
    ExtractorMetadata,
    PatientClaim,
    RecordEvidence,
    TranscriptSpan,
)
from pipeline.stage_05_score_divergence import _compare_fields, aggregate_field_relations


def _claim(**updates) -> PatientClaim:
    values = {
        "claim_id": "claim-test",
        "medication_name": "metoprolol",
        "status": "active",
        "dose_value": 100,
        "dose_unit": "mg",
        "frequency": "daily",
        "route": None,
        "supporting_spans": [
            TranscriptSpan(
                turn_index=0,
                start_char=4,
                end_char=38,
                text="I take metoprolol 100 mg daily.",
            )
        ],
        "confidence": ClaimConfidence(
            level=ConfidenceLevel.NEUTRAL,
            score=0.67,
            rationale="Ordinary assertion.",
        ),
        "first_turn": 0,
        "last_turn": 0,
        "extractor": ExtractorMetadata(provider="stub", model="test", request_id="test-request"),
    }
    values.update(updates)
    return PatientClaim(**values)


def _evidence(identifier: str = "rx-1", **updates) -> RecordEvidence:
    values = {
        "evidence_id": identifier,
        "medication_name": "metoprolol",
        "status": "active",
        "resource_type": "MedicationRequest",
        "resource_id": identifier,
        "source_path": f"MedicationRequest[{identifier}]",
    }
    values.update(updates)
    return RecordEvidence(**values)


def _overall(claim: PatientClaim, evidence: list[RecordEvidence]) -> EvidenceRelation:
    return aggregate_field_relations(_compare_fields(claim, evidence))


def test_name_supported_but_asserted_dose_missing_is_not_support() -> None:
    assert _overall(_claim(frequency=None), [_evidence()]) == EvidenceRelation.SILENT


def test_name_and_dose_supported_but_asserted_frequency_missing_is_not_support() -> None:
    evidence = _evidence(dose_value=100, dose_unit="mg")
    assert _overall(_claim(), [evidence]) == EvidenceRelation.SILENT


def test_all_asserted_fields_supported_is_support() -> None:
    evidence = _evidence(dose_value=100, dose_unit="mg", frequency="daily")
    assert _overall(_claim(), [evidence]) == EvidenceRelation.SUPPORT


def test_one_material_field_contradicted_is_contradiction() -> None:
    evidence = _evidence(dose_value=50, dose_unit="mg", frequency="daily")
    assert _overall(_claim(), [evidence]) == EvidenceRelation.CONTRADICT


def test_competing_resources_with_support_and_contradiction_are_source_conflict() -> None:
    evidence = [
        _evidence("rx-100", dose_value=100, dose_unit="mg", frequency="daily"),
        _evidence("rx-50", dose_value=50, dose_unit="mg", frequency="daily"),
    ]
    assert _overall(_claim(), evidence) == EvidenceRelation.SOURCE_CONFLICT


def test_unasserted_field_silence_is_irrelevant() -> None:
    claim = _claim(dose_value=None, dose_unit=None, frequency=None)
    comparisons = _compare_fields(claim, [_evidence()])
    assert "frequency" not in {item.field for item in comparisons}
    assert aggregate_field_relations(comparisons) == EvidenceRelation.SUPPORT


def test_generic_name_is_supported_by_compatible_rxnorm_salt_name() -> None:
    claim = _claim(dose_value=None, dose_unit=None, frequency=None)
    evidence = _evidence(
        medication_name="24 HR metoprolol succinate 100 MG Extended Release Oral Tablet"
    )
    assert _overall(claim, [evidence]) == EvidenceRelation.SUPPORT


def test_claimed_component_strength_matches_combination_product() -> None:
    claim = _claim(
        medication_name="hydrocodone acetaminophen",
        dose_value=5,
        dose_unit="mg",
        frequency=None,
    )
    evidence = _evidence(
        medication_name="Acetaminophen 300 MG / Hydrocodone Bitartrate 5 MG Oral Tablet",
        dose_value=300,
        dose_unit="mg",
        dose_values=[300, 5],
        dose_units=["mg", "mg"],
    )
    assert _overall(claim, [evidence]) == EvidenceRelation.SUPPORT
