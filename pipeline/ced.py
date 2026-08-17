"""Versioned numeric mappings and the complete CED formula."""

from __future__ import annotations

from pipeline.models import ConfidenceLevel, EvidenceRelation

CED_VERSION = "ced-v1"

CONFIDENCE_SCORE: dict[ConfidenceLevel, float | None] = {
    ConfidenceLevel.EMPHATIC: 1.0,
    ConfidenceLevel.NEUTRAL: 0.67,
    ConfidenceLevel.HEDGED: 0.33,
    ConfidenceLevel.UNCLEAR: None,
}

DIVERGENCE_SCORE: dict[EvidenceRelation, float | None] = {
    EvidenceRelation.SUPPORT: 0.0,
    EvidenceRelation.SILENT: 0.5,
    EvidenceRelation.SOURCE_CONFLICT: 0.75,
    EvidenceRelation.CONTRADICT: 1.0,
    EvidenceRelation.NOT_ASSESSABLE: None,
}


def compute_ced(confidence_score: float | None, divergence_score: float | None) -> float | None:
    if confidence_score is None or divergence_score is None:
        return None
    return round(confidence_score * divergence_score, 4)
