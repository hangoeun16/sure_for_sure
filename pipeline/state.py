"""Inspectable intermediate pipeline state."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from pipeline.input_contract import EncounterInput
from pipeline.models import (
    ActionItem,
    CEDResult,
    ClaimEvidenceLink,
    DialogueTurn,
    DivergenceResult,
    EncounterAnalysis,
    PatientClaim,
    RecordEvidence,
    ResolutionResult,
    SourceProvenance,
)


class PipelineState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    encounter: EncounterInput
    source: SourceProvenance | None = None
    turns: list[DialogueTurn] = Field(default_factory=list)
    claims: list[PatientClaim] = Field(default_factory=list)
    record_evidence: list[RecordEvidence] = Field(default_factory=list)
    links: dict[str, list[ClaimEvidenceLink]] = Field(default_factory=dict)
    divergences: dict[str, DivergenceResult] = Field(default_factory=dict)
    ced_results: dict[str, CEDResult] = Field(default_factory=dict)
    resolutions: dict[str, ResolutionResult] = Field(default_factory=dict)
    actions: list[ActionItem] = Field(default_factory=list)
    report: EncounterAnalysis | None = None
