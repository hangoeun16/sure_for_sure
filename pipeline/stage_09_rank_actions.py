"""Stage 09: rank actionable, scorable items only by CED."""

from __future__ import annotations

from pipeline.models import ActionRoute
from pipeline.state import PipelineState


def run(state: PipelineState) -> PipelineState:
    actionable = [
        item
        for item in state.actions
        if item.route != ActionRoute.NO_ACTION and item.ced_score is not None
    ]
    actionable.sort(
        key=lambda item: (
            -(item.ced_score if item.ced_score is not None else 0.0),
            item.claim_id,
        )
    )
    rank_by_claim = {item.claim_id: rank for rank, item in enumerate(actionable, start=1)}
    state.actions = [
        item.model_copy(update={"rank": rank_by_claim.get(item.claim_id)}) for item in state.actions
    ]
    state.actions.sort(
        key=lambda item: (
            item.route == ActionRoute.NO_ACTION,
            item.rank is None,
            item.rank if item.rank is not None else 10**9,
            item.claim_id,
        )
    )
    return state
