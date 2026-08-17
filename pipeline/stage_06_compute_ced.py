"""Stage 06: multiply claim confidence by record divergence."""

from __future__ import annotations

from pipeline.ced import CED_VERSION, compute_ced
from pipeline.models import CEDResult
from pipeline.state import PipelineState


def run(state: PipelineState) -> PipelineState:
    for claim in state.claims:
        divergence = state.divergences[claim.claim_id]
        confidence_score = claim.confidence.score
        divergence_score = divergence.divergence_score
        score = compute_ced(confidence_score, divergence_score)
        missing = []
        if confidence_score is None:
            missing.append("claim confidence is unclear")
        if divergence_score is None:
            missing.append("record divergence is not assessable")
        state.ced_results[claim.claim_id] = CEDResult(
            claim_id=claim.claim_id,
            confidence_score=confidence_score,
            divergence_score=divergence_score,
            ced_score=score,
            scorable=score is not None,
            abstention_reason="; ".join(missing) or None,
            formula_version=CED_VERSION,
        )
    return state
