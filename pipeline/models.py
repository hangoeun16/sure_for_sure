"""Stable product vocabulary shared by all pipeline stages."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Speaker(StrEnum):
    PATIENT = "PT"
    CLINICIAN = "DR"
    NURSE = "NURSE"
    FAMILY = "FAMILY"
    OTHER = "OTHER"


class DialogueTurn(Model):
    index: int
    speaker: Speaker
    speaker_label: str
    text: str
    start_char: int
    end_char: int


class TranscriptSpan(Model):
    turn_index: int
    start_char: int
    end_char: int
    text: str


class ConfidenceLevel(StrEnum):
    EMPHATIC = "emphatic"
    NEUTRAL = "neutral"
    HEDGED = "hedged"
    UNCLEAR = "unclear"


class ConfidenceCueType(StrEnum):
    BOOSTER = "booster"
    HEDGE = "hedge"
    HESITATION = "hesitation"
    SELF_JUSTIFICATION = "self_justification"
    AUTHORITY = "authority"


class ConfidenceCue(Model):
    type: ConfidenceCueType
    span: TranscriptSpan


class ConfidenceCueWarningCode(StrEnum):
    TYPE_MISMATCH = "cue_type_mismatch"
    OUTSIDE_PATIENT_SUPPORT = "cue_outside_patient_support"
    BRACKETED_ELLIPSIS = "bracketed_ellipsis"


class ConfidenceCueValidationWarning(Model):
    code: ConfidenceCueWarningCode
    attempted_type: ConfidenceCueType
    turn_index: int
    quote: str
    message: str


class ExtractorMetadata(Model):
    provider: str
    model: str
    request_id: str
    schema_version: str = "claim-extraction-v2"
    attempts: int = 1
    usage: dict[str, int] = Field(default_factory=dict)


class ClaimConfidence(Model):
    level: ConfidenceLevel
    score: float | None = Field(default=None, ge=0, le=1)
    cues: list[ConfidenceCue] = Field(default_factory=list)
    validation_warnings: list[ConfidenceCueValidationWarning] = Field(default_factory=list)
    rationale: str


class PatientClaim(Model):
    claim_id: str
    medication_name: str
    status: str | None = None
    dose_value: float | None = None
    dose_unit: str | None = None
    frequency: str | None = None
    route: str | None = None
    negated: bool = False
    negation_span: TranscriptSpan | None = None
    adherence_gap: bool = False
    adherence_span: TranscriptSpan | None = None
    supporting_spans: list[TranscriptSpan] = Field(min_length=1)
    confidence: ClaimConfidence
    first_turn: int
    last_turn: int
    extractor: ExtractorMetadata


class RecordEvidence(Model):
    evidence_id: str
    medication_name: str
    status: str | None = None
    dose_value: float | None = None
    dose_unit: str | None = None
    dose_values: list[float] = Field(default_factory=list)
    dose_units: list[str] = Field(default_factory=list)
    frequency: str | None = None
    route: str | None = None
    resource_type: str
    resource_id: str | None = None
    source_path: str
    effective_time: str | None = None
    patient_reference: str | None = None
    raw_text: str = ""


class ClaimEvidenceLink(Model):
    claim_id: str
    evidence_id: str
    match_type: str
    match_score: float = Field(ge=0, le=1)
    rationale: str


class EvidenceRelation(StrEnum):
    SUPPORT = "support"
    CONTRADICT = "contradict"
    SILENT = "silent"
    NOT_ASSESSABLE = "not_assessable"
    SOURCE_CONFLICT = "source_conflict"


class FieldComparison(Model):
    field: str
    relation: EvidenceRelation
    claim_value: str | float | None
    record_values: list[str | float]
    evidence_ids: list[str]
    rationale: str


class DivergenceResult(Model):
    claim_id: str
    relation: EvidenceRelation
    divergence_score: float | None = Field(default=None, ge=0, le=1)
    disputed_fields: list[str] = Field(default_factory=list)
    field_comparisons: list[FieldComparison]
    supporting_evidence_ids: list[str]
    conflicting_evidence_ids: list[str]
    rationale: str


class CEDResult(Model):
    claim_id: str
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    divergence_score: float | None = Field(default=None, ge=0, le=1)
    ced_score: float | None = Field(default=None, ge=0, le=1)
    scorable: bool
    abstention_reason: str | None = None
    formula_version: str


class ResolutionResult(Model):
    claim_id: str
    resolved: bool
    resolution_type: str | None = None
    resolving_claim_id: str | None = None
    resolution_span: TranscriptSpan | None = None
    resolved_value: str | None = None
    disputed_fields: list[str] = Field(default_factory=list)
    resolved_fields: list[str] = Field(default_factory=list)
    unresolved_fields: list[str] = Field(default_factory=list)
    chart_conflict_remaining: bool = False
    rationale: str

    @model_validator(mode="after")
    def require_consistent_field_bookkeeping(self) -> ResolutionResult:
        disputed = set(self.disputed_fields)
        resolved = set(self.resolved_fields)
        unresolved = set(self.unresolved_fields)

        if len(disputed) != len(self.disputed_fields):
            raise ValueError("disputed_fields must not contain duplicates")
        if len(resolved) != len(self.resolved_fields):
            raise ValueError("resolved_fields must not contain duplicates")
        if len(unresolved) != len(self.unresolved_fields):
            raise ValueError("unresolved_fields must not contain duplicates")
        if resolved & unresolved:
            raise ValueError("resolved_fields and unresolved_fields must be disjoint")
        if resolved | unresolved != disputed:
            raise ValueError(
                "resolved_fields and unresolved_fields must partition disputed_fields"
            )
        if self.resolved and (not disputed or unresolved):
            raise ValueError("resolved results require disputed fields and no unresolved fields")
        if not self.resolved and disputed and not unresolved:
            raise ValueError("unresolved results must retain at least one unresolved field")
        return self


class ActionRoute(StrEnum):
    PATIENT_CLARIFICATION = "patient_clarification"
    CHART_CLEANUP = "chart_cleanup"
    CLINICIAN_REVIEW = "clinician_review"
    NO_ACTION = "no_action"


class ActionItem(Model):
    claim_id: str
    route: ActionRoute
    ced_score: float | None = None
    rank: int | None = None
    recommended_action: str
    routing_rationale: str
    claim: PatientClaim
    divergence: DivergenceResult
    resolution: ResolutionResult


class SourceProvenance(Model):
    source_dataset: str
    source_file: str
    source_record_id: str
    source_record_index: int
    source_sha256: str
    record_sha256: str


class AnalysisSummary(Model):
    claims: int
    patient_clarifications: int
    chart_cleanup: int
    clinician_review: int
    no_action: int


class EncounterAnalysis(Model):
    encounter_id: str
    source: SourceProvenance | None = None
    summary: AnalysisSummary
    turns: list[DialogueTurn]
    claims: list[PatientClaim]
    record_evidence: list[RecordEvidence]
    links: dict[str, list[ClaimEvidenceLink]]
    divergences: dict[str, DivergenceResult]
    ced_results: dict[str, CEDResult]
    resolutions: dict[str, ResolutionResult]
    actions: list[ActionItem]


class ProviderQuote(Model):
    turn_index: int
    quote: str


class ProviderConfidenceCue(Model):
    type: ConfidenceCueType
    turn_index: int
    quote: str


class ProviderClaim(Model):
    medication_name: str = Field(min_length=1)
    status: str | None = None
    dose_value: float | None = None
    dose_unit: str | None = None
    frequency: str | None = None
    route: str | None = None
    negated: bool = False
    negation_quote: ProviderQuote | None = None
    confidence_cues: list[ProviderConfidenceCue] = Field(default_factory=list)
    supporting_quotes: list[ProviderQuote] = Field(min_length=1)
    adherence_gap: bool = False
    adherence_quote: ProviderQuote | None = None


class ProviderExtractionResult(Model):
    claims: list[ProviderClaim]
    metadata: ExtractorMetadata
