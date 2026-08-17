"""Stage 07: detect later patient-confirmed resolution without changing historical CED."""

from __future__ import annotations

from pipeline.models import (
    ConfidenceLevel,
    DivergenceResult,
    EvidenceRelation,
    FieldComparison,
    PatientClaim,
    ResolutionResult,
    Speaker,
)
from pipeline.normalization import (
    medication_names_compatible,
    normalize_dose_unit,
    normalize_frequency,
    normalize_medication_name,
    normalize_route,
    normalize_status,
)
from pipeline.state import PipelineState

_CONFIDENCE_ORDER = {
    ConfidenceLevel.UNCLEAR: 0,
    ConfidenceLevel.HEDGED: 1,
    ConfidenceLevel.NEUTRAL: 2,
    ConfidenceLevel.EMPHATIC: 3,
}


def run(state: PipelineState) -> PipelineState:
    for claim in state.claims:
        divergence = state.divergences[claim.claim_id]
        disputed_fields = set(divergence.disputed_fields)
        later = sorted(
            _later_candidates(claim, state),
            key=lambda item: (item.first_turn, item.claim_id),
        )
        evaluated = [
            (
                candidate,
                disputed_fields
                & _materially_established_fields(
                    candidate,
                    state.divergences[candidate.claim_id],
                ),
            )
            for candidate in later
        ]
        resolving_pair = next(
            (item for item in evaluated if disputed_fields and disputed_fields <= item[1]),
            None,
        )
        # Resolution is deliberately single-claim. If no candidate establishes every
        # field, one deterministic best candidate owns all partial bookkeeping; fields
        # from multiple rejected candidates are never unioned.
        selected_pair = resolving_pair or max(
            evaluated,
            key=lambda item: len(item[1]),
            default=None,
        )
        resolving = resolving_pair[0] if resolving_pair else None
        resolved_fields = selected_pair[1] if selected_pair else set()
        unresolved_fields = disputed_fields - resolved_fields
        chart_remaining = bool(
            resolving
            and divergence.relation
            in {EvidenceRelation.SOURCE_CONFLICT, EvidenceRelation.CONTRADICT}
        )
        if not disputed_fields:
            rationale = "The original claim has no disputed material fields."
        elif resolving:
            rationale = (
                f"Later patient claim {resolving.claim_id} materially establishes all "
                f"disputed fields: {', '.join(sorted(resolved_fields))}."
            )
        elif selected_pair and resolved_fields:
            candidate = selected_pair[0]
            rationale = (
                f"Best single later patient claim {candidate.claim_id} materially establishes "
                f"{', '.join(sorted(resolved_fields))}; still unresolved: "
                f"{', '.join(sorted(unresolved_fields))}."
            )
        elif later:
            rationale = (
                "Later same-medication dialogue does not establish a chart-consistent "
                f"value for any disputed field; still unresolved: "
                f"{', '.join(sorted(unresolved_fields))}."
            )
        else:
            rationale = "No later patient-grounded claim addresses this discrepancy."
        state.resolutions[claim.claim_id] = ResolutionResult(
            claim_id=claim.claim_id,
            resolved=bool(disputed_fields) and resolving is not None,
            resolution_type="later_patient_confirmation" if resolving else None,
            resolving_claim_id=resolving.claim_id if resolving else None,
            resolution_span=(resolving.supporting_spans[-1] if resolving else None),
            resolved_value=(_regimen(resolving) if resolving else None),
            disputed_fields=sorted(disputed_fields),
            resolved_fields=sorted(resolved_fields),
            unresolved_fields=sorted(unresolved_fields),
            chart_conflict_remaining=chart_remaining,
            rationale=rationale,
        )
    return state


def _later_candidates(claim: PatientClaim, state: PipelineState) -> list[PatientClaim]:
    return [
        candidate
        for candidate in state.claims
        if candidate.claim_id != claim.claim_id
        and normalize_medication_name(candidate.medication_name)
        == normalize_medication_name(claim.medication_name)
        and candidate.first_turn > claim.last_turn
        and _patient_grounded(candidate, state)
        and _CONFIDENCE_ORDER[candidate.confidence.level]
        >= _CONFIDENCE_ORDER[claim.confidence.level]
        and _establishes_regimen(candidate)
    ]


def _patient_grounded(claim: PatientClaim, state: PipelineState) -> bool:
    return any(
        state.turns[span.turn_index].speaker == Speaker.PATIENT for span in claim.supporting_spans
    )


def _establishes_regimen(claim: PatientClaim) -> bool:
    return claim.status not in {None, "uncertain"} and claim.confidence.level in {
        ConfidenceLevel.NEUTRAL,
        ConfidenceLevel.EMPHATIC,
    }


def _materially_established_fields(
    claim: PatientClaim,
    divergence: DivergenceResult,
) -> set[str]:
    """Return asserted fields with chart-consistent evidence for this one claim."""
    asserted = {
        field
        for field in ("medication_name", "status", "dose_value", "dose_unit", "frequency", "route")
        if getattr(claim, field) is not None
    }
    return {
        comparison.field
        for comparison in divergence.field_comparisons
        if comparison.field in asserted and _has_supporting_record_value(comparison)
    }


def _has_supporting_record_value(comparison: FieldComparison) -> bool:
    if comparison.relation == EvidenceRelation.SUPPORT:
        return True
    if comparison.relation != EvidenceRelation.SOURCE_CONFLICT:
        return False

    normalizers = {
        "medication_name": normalize_medication_name,
        "dose_value": _normalize_number,
        "dose_unit": normalize_dose_unit,
        "frequency": normalize_frequency,
        "route": normalize_route,
        "status": normalize_status,
    }
    normalizer = normalizers.get(comparison.field)
    if normalizer is None or comparison.claim_value is None:
        return False
    normalized_claim = normalizer(comparison.claim_value)
    normalized_records = [
        value
        for record_value in comparison.record_values
        if (value := normalizer(record_value)) is not None
    ]
    if normalized_claim is None:
        return False
    if comparison.field == "medication_name":
        return any(
            medication_names_compatible(normalized_claim, value)
            for value in normalized_records
        )
    return normalized_claim in normalized_records


def _normalize_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        return float(value)
    raise TypeError(f"Unsupported numeric value: {type(value).__name__}")


def _regimen(claim: PatientClaim) -> str:
    parts = [claim.medication_name, claim.status or ""]
    if claim.dose_value is not None:
        parts.append(f"{claim.dose_value:g} {claim.dose_unit or ''}".strip())
    if claim.frequency:
        parts.append(claim.frequency)
    return " ".join(part for part in parts if part)
