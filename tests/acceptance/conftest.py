from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from backend.repository import canonical_record_hash
from pipeline.input_contract import EncounterInput
from pipeline.models import SourceProvenance
from pipeline.providers import StubClaimExtractionProvider
from pipeline.runner import run_pipeline

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "acceptance" / "cases.json"


@pytest.fixture(scope="session")
def acceptance_cases() -> dict[str, dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def build_record(case_name: str, case: dict) -> dict:
    patient_id = case["patient_id"]
    requests = []
    for medication in case["medications"]:
        requests.append(
            {
                "resourceType": "MedicationRequest",
                "id": medication["id"],
                "status": medication["status"],
                "authoredOn": "2026-01-10",
                "subject": {"reference": f"Patient/{patient_id}"},
                "medicationCodeableConcept": {"text": medication["text"]},
                "dosageInstruction": [{"text": medication.get("frequency", "")}],
            }
        )
    return {
        "id": case_name,
        "metadata": {"patient_id": patient_id, "visit_title": f"Acceptance {case_name}"},
        "patient_context": {"longitudinal_summary": {"medication_labels": []}},
        "encounter_fhir": {"related_resources": {"MedicationRequest": requests}},
        "transcript": case["transcript"],
        "note": "",
        "after_visit_summary": "",
        "after_visit_summary_provenance": {},
    }


def _cue_quote(transcript: str, cue: str | None) -> dict | None:
    if not cue:
        return None
    for turn_index, line in enumerate(transcript.splitlines()):
        text = line.split(":", 1)[1].lstrip() if ":" in line else line
        if cue in text:
            return {"turn_index": turn_index, "quote": cue}
    raise AssertionError(f"Fixture cue is not present verbatim: {cue!r}")


def _confidence_cues(transcript: str, cue: str | None) -> list[dict]:
    grounded = _cue_quote(transcript, cue)
    return [{"type": "hedge", **grounded}] if grounded else []


def provider_response(case: dict) -> dict:
    claims = []
    for item in case["provider_output"]["claims"]:
        uncertainty = item.get("uncertainty_cue")
        adherence = item.get("adherence")
        claims.append(
            {
                "medication_name": item["medication_name"],
                "status": item.get("status"),
                "dose_value": item.get("dose_value"),
                "dose_unit": item.get("dose_unit"),
                "frequency": item.get("frequency"),
                "route": item.get("route"),
                "negated": item.get("negated", False),
                "negation_quote": _cue_quote(case["transcript"], item.get("negation_cue")),
                "confidence_cues": _confidence_cues(case["transcript"], uncertainty),
                "supporting_quotes": item["supporting_evidence"],
                "adherence_gap": bool(adherence and adherence.get("status") == "gap"),
                "adherence_quote": _cue_quote(
                    case["transcript"], adherence.get("quote") if adherence else None
                ),
            }
        )
    return {"claims": claims}


@pytest.fixture
def analyze_case(acceptance_cases):
    def _analyze(case_name: str):
        case = acceptance_cases[case_name]
        raw = build_record(case_name, case)
        encounter = EncounterInput.model_validate(raw)
        source = SourceProvenance(
            source_dataset="acceptance-synthetic",
            source_record_id=case_name,
            source_record_index=sorted(acceptance_cases).index(case_name),
            source_file="tests/fixtures/acceptance/cases.json",
            source_sha256=hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest(),
            record_sha256=canonical_record_hash(raw),
        )
        analysis = run_pipeline(
            encounter,
            StubClaimExtractionProvider(provider_response(case)),
            source=source,
        )
        return raw, analysis

    return _analyze
