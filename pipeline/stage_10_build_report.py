"""Stage 10: assemble structured clinician-facing JSON."""

from __future__ import annotations

from collections import Counter

from pipeline.models import AnalysisSummary, EncounterAnalysis
from pipeline.state import PipelineState


def run(state: PipelineState) -> PipelineState:
    counts = Counter(item.route.value for item in state.actions)
    state.report = EncounterAnalysis(
        encounter_id=state.encounter.id,
        source=state.source,
        summary=AnalysisSummary(
            claims=len(state.claims),
            patient_clarifications=counts["patient_clarification"],
            chart_cleanup=counts["chart_cleanup"],
            clinician_review=counts["clinician_review"],
            no_action=counts["no_action"],
        ),
        turns=state.turns,
        claims=state.claims,
        record_evidence=state.record_evidence,
        links=state.links,
        divergences=state.divergences,
        ced_results=state.ced_results,
        resolutions=state.resolutions,
        actions=state.actions,
    )
    return state
