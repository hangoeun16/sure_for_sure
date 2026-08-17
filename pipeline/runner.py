"""The complete, explicit single-encounter product workflow."""

from __future__ import annotations

from pipeline import (
    stage_01_parse_dialogue,
    stage_02_extract_claims,
    stage_03_extract_record_evidence,
    stage_04_link_claims_to_evidence,
    stage_05_score_divergence,
    stage_06_compute_ced,
    stage_07_detect_resolution,
    stage_08_route_actions,
    stage_09_rank_actions,
    stage_10_build_report,
)
from pipeline.input_contract import EncounterInput
from pipeline.models import EncounterAnalysis, SourceProvenance
from pipeline.providers.base import ClaimExtractionProvider
from pipeline.state import PipelineState


def run_pipeline(
    encounter: EncounterInput,
    provider: ClaimExtractionProvider,
    *,
    source: SourceProvenance | None = None,
) -> EncounterAnalysis:
    state = PipelineState(encounter=encounter, source=source)
    state = stage_01_parse_dialogue.run(state)
    state = stage_02_extract_claims.run(state, provider)
    state = stage_03_extract_record_evidence.run(state)
    state = stage_04_link_claims_to_evidence.run(state)
    state = stage_05_score_divergence.run(state)
    state = stage_06_compute_ced.run(state)
    state = stage_07_detect_resolution.run(state)
    state = stage_08_route_actions.run(state)
    state = stage_09_rank_actions.run(state)
    state = stage_10_build_report.run(state)
    assert state.report is not None
    return state.report
