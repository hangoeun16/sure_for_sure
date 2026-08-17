from __future__ import annotations

from copy import deepcopy

import pytest
from pipeline.input_contract import EncounterInput
from pipeline.stage_03_extract_record_evidence import PatientMismatchError, run
from pipeline.state import PipelineState


def _encounter() -> EncounterInput:
    return EncounterInput(
        id="record-evidence-test",
        metadata={"patient_id": "patient-one"},
        patient_context={"longitudinal_summary": {"medication_labels": []}},
        encounter_fhir={
            "related_resources": {
                "MedicationRequest": [
                    {
                        "resourceType": "MedicationRequest",
                        "id": "rx-unseen",
                        "status": "active",
                        "authoredOn": "2026-02-01",
                        "subject": {"reference": "Patient/patient-one"},
                        "medicationCodeableConcept": {"text": "rivaroxaban 20 MG Oral Tablet"},
                        "dosageInstruction": [
                            {"text": "Take one tablet with dinner", "route": {"text": "oral route"}}
                        ],
                    }
                ]
            }
        },
        transcript="PT: I take rivaroxaban.",
        note="",
        after_visit_summary="",
        after_visit_summary_provenance={},
    )


def test_fhir_retrieval_normalizes_fields_and_preserves_location() -> None:
    evidence = run(PipelineState(encounter=_encounter())).record_evidence
    assert len(evidence) == 1
    item = evidence[0]
    assert item.medication_name == "rivaroxaban"
    assert item.dose_value == 20
    assert item.dose_unit == "mg"
    assert item.frequency == "with dinner"
    assert item.route == "oral"
    assert item.effective_time == "2026-02-01"
    assert item.resource_id == "rx-unseen"
    assert item.source_path == "encounter_fhir.related_resources.MedicationRequest[0]"


def test_explicit_cross_patient_resource_is_rejected() -> None:
    payload = _encounter().model_dump()
    payload["encounter_fhir"]["related_resources"]["MedicationRequest"][0]["subject"] = {
        "reference": "Patient/patient-two"
    }
    with pytest.raises(PatientMismatchError, match="not encounter patient"):
        run(PipelineState(encounter=EncounterInput.model_validate(payload)))


def test_dose_quantity_is_used_when_text_has_no_strength() -> None:
    payload = _encounter().model_dump()
    request = payload["encounter_fhir"]["related_resources"]["MedicationRequest"][0]
    request["medicationCodeableConcept"]["text"] = "rivaroxaban oral tablet"
    request["dosageInstruction"][0]["doseAndRate"] = [
        {"doseQuantity": {"value": 20, "unit": "milligrams"}}
    ]
    evidence = run(PipelineState(encounter=EncounterInput.model_validate(payload))).record_evidence
    assert evidence[0].dose_value == 20
    assert evidence[0].dose_unit == "mg"


def test_unresolved_medication_reference_is_retained_not_dropped() -> None:
    payload = deepcopy(_encounter().model_dump())
    request = payload["encounter_fhir"]["related_resources"]["MedicationRequest"][0]
    request.pop("medicationCodeableConcept")
    request["medicationReference"] = {"reference": "Medication/not-in-bundle"}
    evidence = run(PipelineState(encounter=EncounterInput.model_validate(payload))).record_evidence
    assert evidence[0].resource_id == "rx-unseen"
    assert evidence[0].medication_name == "medication not in bundle"


def test_longitudinal_label_infers_route_from_formulation_text() -> None:
    payload = _encounter().model_dump()
    payload["encounter_fhir"] = {"related_resources": {}}
    payload["patient_context"] = {
        "longitudinal_summary": {"medication_labels": ["Hydrocortisone 10 MG/ML Topical Cream"]}
    }
    evidence = run(PipelineState(encounter=EncounterInput.model_validate(payload))).record_evidence
    assert evidence[0].route == "topical"


def test_combination_product_preserves_all_strength_values() -> None:
    payload = _encounter().model_dump()
    payload["encounter_fhir"] = {"related_resources": {}}
    payload["patient_context"] = {
        "longitudinal_summary": {
            "medication_labels": ["Acetaminophen 300 MG / Hydrocodone Bitartrate 5 MG Oral Tablet"]
        }
    }
    evidence = run(PipelineState(encounter=EncounterInput.model_validate(payload))).record_evidence
    assert evidence[0].dose_values == [300.0, 5.0]
    assert evidence[0].dose_units == ["mg", "mg"]
