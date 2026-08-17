"""Stage 03: collect same-patient medication evidence without adjudicating it."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from pipeline.models import RecordEvidence
from pipeline.normalization import (
    normalize_dose_unit,
    normalize_frequency,
    normalize_medication_name,
    normalize_route,
    normalize_status,
)
from pipeline.state import PipelineState

MEDICATION_TYPES = (
    "MedicationRequest",
    "MedicationStatement",
    "MedicationAdministration",
    "Medication",
)
DOSE_RE = re.compile(r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mg|mcg|µg|g|ml)\b", re.I)


class PatientMismatchError(ValueError):
    pass


def run(state: PipelineState) -> PipelineState:
    expected_patient = str(state.encounter.metadata.get("patient_id") or "")
    related = state.encounter.encounter_fhir.get("related_resources", {})
    medication_lookup = _medication_lookup(related.get("Medication", []))
    evidence: list[RecordEvidence] = []
    for resource_type in MEDICATION_TYPES:
        resources = related.get(resource_type, [])
        if isinstance(resources, dict):
            resources = [resources]
        for index, resource in enumerate(resources or []):
            if not isinstance(resource, dict):
                continue
            path = f"encounter_fhir.related_resources.{resource_type}[{index}]"
            evidence.append(
                _resource_evidence(
                    resource, resource_type, path, expected_patient, medication_lookup
                )
            )
    labels = state.encounter.patient_context.get("longitudinal_summary", {}).get(
        "medication_labels", []
    )
    if isinstance(labels, dict):
        labels = list(labels.values())
    for index, label in enumerate(labels or []):
        item = label if isinstance(label, dict) else {"text": str(label)}
        raw = _first_text(item.get("text"), item.get("label"), item.get("name"))
        if not raw:
            continue
        name, dose, unit = _name_and_dose(raw)
        dose_values, dose_units = _dose_values(raw)
        path = f"patient_context.longitudinal_summary.medication_labels[{index}]"
        evidence.append(
            RecordEvidence(
                evidence_id=_evidence_id(None, path),
                medication_name=name or "unresolved medication",
                status=normalize_status(item.get("status")),
                dose_value=dose,
                dose_unit=unit,
                dose_values=dose_values,
                dose_units=dose_units,
                frequency=normalize_frequency(item.get("frequency")),
                route=normalize_route(item.get("route")) or _route_from_medication_text(raw),
                resource_type="LongitudinalMedicationLabel",
                source_path=path,
                effective_time=_first_text(item.get("effective_time"), item.get("date")),
                patient_reference=expected_patient or None,
                raw_text=raw,
            )
        )
    state.record_evidence = evidence
    return state


def _resource_evidence(
    resource: dict[str, Any],
    resource_type: str,
    path: str,
    expected: str,
    medication_lookup: dict[str, str],
) -> RecordEvidence:
    patient_reference = _patient_reference(resource)
    if patient_reference and expected:
        actual = patient_reference.removeprefix("urn:uuid:").rsplit("/", 1)[-1]
        if actual != expected:
            raise PatientMismatchError(
                f"{path} references {patient_reference}, not encounter patient {expected}."
            )
    raw = _medication_text(resource, medication_lookup)
    name, dose, unit = _name_and_dose(raw)
    dose_values, dose_units = _dose_values(raw)
    instruction = _first_instruction(resource)
    quantity = _dose_quantity(instruction)
    if dose is None and quantity:
        dose, unit = quantity
        dose_values = [dose]
        dose_units = [unit] if unit else []
    frequency = _frequency(instruction)
    route = _concept_text(instruction.get("route")) if instruction else None
    resource_id = str(resource.get("id")) if resource.get("id") is not None else None
    effective = _first_text(
        resource.get("authoredOn"),
        resource.get("effectiveDateTime"),
        resource.get("occurrenceDateTime"),
        _nested(resource, "effectivePeriod", "start"),
        _nested(resource, "validityPeriod", "start"),
    )
    return RecordEvidence(
        evidence_id=_evidence_id(resource_id, path),
        medication_name=name or "unresolved medication reference",
        status=normalize_status(resource.get("status")),
        dose_value=dose,
        dose_unit=unit,
        dose_values=dose_values,
        dose_units=dose_units,
        frequency=normalize_frequency(frequency),
        route=normalize_route(route) or _route_from_medication_text(raw),
        resource_type=resource_type,
        resource_id=resource_id,
        source_path=path,
        effective_time=effective,
        patient_reference=patient_reference,
        raw_text=raw,
    )


def _medication_lookup(resources: object) -> dict[str, str]:
    values = (
        resources
        if isinstance(resources, list)
        else [resources]
        if isinstance(resources, dict)
        else []
    )
    result = {}
    for item in values:
        if isinstance(item, dict) and item.get("id"):
            result[str(item["id"])] = (
                _first_text(_concept_text(item.get("code")), item.get("text"), item.get("name"))
                or ""
            )
    return result


def _medication_text(resource: dict[str, Any], lookup: dict[str, str]) -> str:
    direct = _first_text(
        _concept_text(resource.get("medicationCodeableConcept")),
        _concept_text(resource.get("medication")),
        resource.get("medicationCode"),
        resource.get("medicationName"),
        resource.get("description"),
    )
    if direct:
        return direct
    reference = resource.get("medicationReference") or (
        resource.get("medication")
        if isinstance(resource.get("medication"), dict) and resource["medication"].get("reference")
        else None
    )
    if isinstance(reference, dict):
        key = str(reference.get("reference", "")).rsplit("/", 1)[-1]
        return lookup.get(key, str(reference.get("display") or reference.get("reference") or ""))
    return ""


def _concept_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return None
    if value.get("text"):
        return str(value["text"])
    if value.get("display"):
        return str(value["display"])
    coding = value.get("coding")
    if isinstance(coding, list):
        for item in coding:
            if isinstance(item, dict) and (item.get("display") or item.get("code")):
                return str(item.get("display") or item.get("code"))
    return None


def _name_and_dose(raw: str) -> tuple[str, float | None, str | None]:
    match = DOSE_RE.search(raw)
    dose = float(match.group("value")) if match else None
    unit = normalize_dose_unit(match.group("unit")) if match else None
    return normalize_medication_name(raw), dose, unit


def _dose_values(raw: str) -> tuple[list[float], list[str]]:
    matches = list(DOSE_RE.finditer(raw))
    return (
        [float(match.group("value")) for match in matches],
        [normalize_dose_unit(match.group("unit")) or "" for match in matches],
    )


def _route_from_medication_text(raw: str) -> str | None:
    lowered = raw.lower()
    if "sublingual" in lowered:
        return "sublingual"
    if "topical" in lowered:
        return "topical"
    if "oral" in lowered:
        return "oral"
    if "inject" in lowered or "auto-injector" in lowered:
        return "injection"
    return None


def _first_instruction(resource: dict[str, Any]) -> dict[str, Any]:
    instructions = resource.get("dosageInstruction") or resource.get("dosage")
    if isinstance(instructions, list) and instructions and isinstance(instructions[0], dict):
        return instructions[0]
    if isinstance(instructions, dict):
        return instructions
    return {}


def _dose_quantity(instruction: dict[str, Any]) -> tuple[float, str | None] | None:
    rates = instruction.get("doseAndRate")
    candidates = rates if isinstance(rates, list) else [rates] if isinstance(rates, dict) else []
    for item in candidates:
        quantity = item.get("doseQuantity", {}) if isinstance(item, dict) else {}
        if isinstance(quantity, dict) and quantity.get("value") is not None:
            return float(quantity["value"]), normalize_dose_unit(
                quantity.get("unit") or quantity.get("code")
            )
    return None


def _frequency(instruction: dict[str, Any]) -> str | None:
    text = _first_text(instruction.get("text"), instruction.get("patientInstruction"))
    if text:
        lowered = text.lower()
        for phrase in (
            "every morning",
            "each morning",
            "with dinner",
            "twice daily",
            "once daily",
            "daily",
        ):
            if phrase in lowered:
                return phrase
    repeat = _nested(instruction, "timing", "repeat")
    if isinstance(repeat, dict) and repeat.get("frequency") and repeat.get("period"):
        frequency, period, unit = (
            repeat["frequency"],
            repeat["period"],
            repeat.get("periodUnit"),
        )
        if frequency == 1 and period == 1 and unit == "d":
            return "daily"
        if frequency == 2 and period == 1 and unit == "d":
            return "twice daily"
    return text


def _patient_reference(resource: dict[str, Any]) -> str | None:
    for key in ("subject", "patient"):
        value = resource.get(key)
        if isinstance(value, dict) and value.get("reference"):
            return str(value["reference"])
    return None


def _nested(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_text(*values: object) -> str | None:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _evidence_id(resource_id: str | None, path: str) -> str:
    return resource_id or f"evidence-{hashlib.sha256(path.encode()).hexdigest()[:12]}"
