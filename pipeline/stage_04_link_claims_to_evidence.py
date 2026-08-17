"""Stage 04: deterministically link medication claims to record entries."""

from __future__ import annotations

from pipeline.models import ClaimEvidenceLink
from pipeline.normalization import (
    medication_name_tokens,
    medication_names_compatible,
    normalize_medication_name,
)
from pipeline.state import PipelineState


def run(state: PipelineState) -> PipelineState:
    state.links = {}
    for claim in state.claims:
        links: list[ClaimEvidenceLink] = []
        claim_name = normalize_medication_name(claim.medication_name)
        claim_tokens = medication_name_tokens(claim_name)
        for evidence in state.record_evidence:
            evidence_name = normalize_medication_name(evidence.medication_name)
            evidence_tokens = medication_name_tokens(evidence_name)
            if claim_name and claim_name == evidence_name:
                score, match_type = 1.0, "normalized_exact"
            else:
                denominator = min(len(claim_tokens), len(evidence_tokens))
                overlap = len(claim_tokens & evidence_tokens) / denominator if denominator else 0.0
                if not medication_names_compatible(claim_name, evidence_name):
                    continue
                score, match_type = round(overlap, 4), "token_compatible"
            links.append(
                ClaimEvidenceLink(
                    claim_id=claim.claim_id,
                    evidence_id=evidence.evidence_id,
                    match_type=match_type,
                    match_score=score,
                    rationale=(
                        "Medication identity matched by "
                        f"{match_type.replace('_', ' ')} normalization."
                    ),
                )
            )
        state.links[claim.claim_id] = sorted(
            links, key=lambda item: (-item.match_score, item.evidence_id)
        )
    return state
