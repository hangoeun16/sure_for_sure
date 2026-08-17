"""One canonical rule for combining field-level record evidence."""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.models import EvidenceRelation


@dataclass(frozen=True)
class FieldEvidence:
    relation: EvidenceRelation
    evidence_id: str | None = None


def combine_evidence(items: list[FieldEvidence]) -> EvidenceRelation:
    if not items:
        return EvidenceRelation.SILENT
    relations = {item.relation for item in items}
    if EvidenceRelation.SOURCE_CONFLICT in relations:
        return EvidenceRelation.SOURCE_CONFLICT
    if EvidenceRelation.SUPPORT in relations and EvidenceRelation.CONTRADICT in relations:
        return EvidenceRelation.SOURCE_CONFLICT
    if EvidenceRelation.CONTRADICT in relations:
        return EvidenceRelation.CONTRADICT
    if EvidenceRelation.SUPPORT in relations:
        return EvidenceRelation.SUPPORT
    if relations == {EvidenceRelation.NOT_ASSESSABLE}:
        return EvidenceRelation.NOT_ASSESSABLE
    return EvidenceRelation.SILENT
