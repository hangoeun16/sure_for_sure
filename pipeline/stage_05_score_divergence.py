"""Stage 05: compare linked evidence field by field and score record divergence."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from pipeline.ced import DIVERGENCE_SCORE
from pipeline.evidence import FieldEvidence, combine_evidence
from pipeline.models import (
    DivergenceResult,
    EvidenceRelation,
    FieldComparison,
    PatientClaim,
    RecordEvidence,
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

ComparableValue = str | float
Normalizer = Callable[[object], ComparableValue | None]


def run(state: PipelineState) -> PipelineState:
    evidence_by_id = {item.evidence_id: item for item in state.record_evidence}
    for claim in state.claims:
        linked = [evidence_by_id[link.evidence_id] for link in state.links.get(claim.claim_id, [])]
        comparisons = _compare_fields(claim, linked)
        relation = aggregate_field_relations(comparisons)
        disputed_fields = sorted(
            item.field for item in comparisons if item.relation != EvidenceRelation.SUPPORT
        )
        supporting = sorted(
            {
                eid
                for item in comparisons
                if item.relation == EvidenceRelation.SUPPORT
                for eid in item.evidence_ids
            }
        )
        conflicting = sorted(
            {
                eid
                for item in comparisons
                if item.relation in {EvidenceRelation.CONTRADICT, EvidenceRelation.SOURCE_CONFLICT}
                for eid in item.evidence_ids
            }
        )
        rationale = {
            EvidenceRelation.SUPPORT: (
                "Linked record evidence accords with every assessable claimed attribute."
            ),
            EvidenceRelation.CONTRADICT: (
                "At least one assessable claimed attribute is directly contradicted "
                "by linked record evidence."
            ),
            EvidenceRelation.SILENT: "The available record does not verify or deny the claim.",
            EvidenceRelation.SOURCE_CONFLICT: (
                "Linked record entries conflict with one another and cannot be safely adjudicated."
            ),
            EvidenceRelation.NOT_ASSESSABLE: (
                "The claim/evidence comparison is not defensible enough to quantify."
            ),
        }[relation]
        state.divergences[claim.claim_id] = DivergenceResult(
            claim_id=claim.claim_id,
            relation=relation,
            divergence_score=DIVERGENCE_SCORE[relation],
            disputed_fields=disputed_fields,
            field_comparisons=comparisons,
            supporting_evidence_ids=supporting,
            conflicting_evidence_ids=conflicting,
            rationale=rationale,
        )
    return state


def aggregate_field_relations(comparisons: list[FieldComparison]) -> EvidenceRelation:
    """Aggregate only fields asserted by the patient into one claim relation.

    `_compare_fields` omits patient-unasserted fields. Full support therefore requires
    every returned comparison to be supported; silence on any asserted material field
    makes the overall claim silent/not verifiable rather than supported.
    """
    if not comparisons:
        return EvidenceRelation.NOT_ASSESSABLE
    relations = {item.relation for item in comparisons}
    if EvidenceRelation.SOURCE_CONFLICT in relations:
        return EvidenceRelation.SOURCE_CONFLICT
    if EvidenceRelation.CONTRADICT in relations:
        return EvidenceRelation.CONTRADICT
    if EvidenceRelation.NOT_ASSESSABLE in relations:
        return EvidenceRelation.NOT_ASSESSABLE
    if EvidenceRelation.SILENT in relations:
        return EvidenceRelation.SILENT
    if relations == {EvidenceRelation.SUPPORT}:
        return EvidenceRelation.SUPPORT
    return EvidenceRelation.NOT_ASSESSABLE


def _compare_fields(claim: PatientClaim, evidence: list[RecordEvidence]) -> list[FieldComparison]:
    if not evidence:
        return [
            FieldComparison(
                field="medication_name",
                relation=EvidenceRelation.SILENT,
                claim_value=claim.medication_name,
                record_values=[],
                evidence_ids=[],
                rationale="No same-medication record entry was linked.",
            )
        ]
    fields: list[tuple[str, ComparableValue | None, Normalizer]] = [
        ("medication_name", claim.medication_name, normalize_medication_name),
        (
            "dose_value",
            claim.dose_value,
            _normalize_number,
        ),
        ("dose_unit", claim.dose_unit, normalize_dose_unit),
        ("frequency", claim.frequency, normalize_frequency),
        ("route", claim.route, normalize_route),
        ("status", claim.status, normalize_status),
    ]
    comparisons = []
    for field, claim_value, normalizer in fields:
        if claim_value is None:
            continue
        record_items: list[tuple[str, list[ComparableValue]]] = []
        for item in evidence:
            values: list[ComparableValue]
            if field == "dose_value" and item.dose_values:
                values = list(item.dose_values)
            elif field == "dose_unit" and item.dose_units:
                values = list(item.dose_units)
            else:
                value = cast(ComparableValue | None, getattr(item, field))
                values = [value] if value is not None else []
            if values:
                record_items.append((item.evidence_id, values))
        normalized_claim = normalizer(claim_value)
        normalized_values: list[tuple[str, list[ComparableValue]]] = []
        for evidence_id, values in record_items:
            normalized = [result for value in values if (result := normalizer(value)) is not None]
            if normalized:
                normalized_values.append((evidence_id, normalized))
        flattened_values = [value for _, values in normalized_values for value in values]
        distinct = set(flattened_values)
        observations: list[FieldEvidence] = []
        if not normalized_values:
            relation = EvidenceRelation.SILENT
        else:
            for evidence_id, values in normalized_values:
                matches = any(
                    medication_names_compatible(normalized_claim, value)
                    if field == "medication_name"
                    else value == normalized_claim
                    for value in values
                )
                observations.append(
                    FieldEvidence(
                        EvidenceRelation.SUPPORT if matches else EvidenceRelation.CONTRADICT,
                        evidence_id,
                    )
                )
            relation = combine_evidence(observations)
            if (
                field != "medication_name"
                and len(normalized_values) > 1
                and len(distinct) > 1
                and relation == EvidenceRelation.CONTRADICT
            ):
                relation = EvidenceRelation.SOURCE_CONFLICT
        rationale = {
            EvidenceRelation.SUPPORT: f"All available {field} evidence matches the claim.",
            EvidenceRelation.CONTRADICT: f"Available {field} evidence differs from the claim.",
            EvidenceRelation.SILENT: f"The record does not state {field}.",
            EvidenceRelation.SOURCE_CONFLICT: (
                f"Record entries contain incompatible {field} values."
            ),
            EvidenceRelation.NOT_ASSESSABLE: f"{field} cannot be assessed.",
        }[relation]
        comparisons.append(
            FieldComparison(
                field=field,
                relation=relation,
                claim_value=claim_value,
                record_values=[value for _, values in record_items for value in values],
                evidence_ids=[eid for eid, _ in record_items],
                rationale=rationale,
            )
        )
    return comparisons or [
        FieldComparison(
            field="claim",
            relation=EvidenceRelation.NOT_ASSESSABLE,
            claim_value=None,
            record_values=[],
            evidence_ids=[item.evidence_id for item in evidence],
            rationale="The claim contains no comparable medication attributes.",
        )
    ]


def _normalize_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        return float(value)
    raise TypeError(f"Unsupported numeric value: {type(value).__name__}")
