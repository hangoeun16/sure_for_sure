export type Route = "patient_clarification" | "chart_cleanup" | "clinician_review" | "no_action";
export type Relation = "support" | "contradict" | "silent" | "not_assessable" | "source_conflict";

export interface EncounterListItem { id: string; index: number; title: string; date?: string; visit_type?: string; }
export interface Span { turn_index: number; start_char: number; end_char: number; text: string; }
export interface Turn { index: number; speaker: string; speaker_label: string; text: string; start_char: number; end_char: number; }
export interface ConfidenceCue { type: "booster" | "hedge" | "hesitation" | "self_justification" | "authority"; span: Span; }
export interface ConfidenceCueValidationWarning { code: "cue_type_mismatch" | "cue_outside_patient_support" | "bracketed_ellipsis"; attempted_type: ConfidenceCue["type"]; turn_index: number; quote: string; message: string; }
export interface Confidence { level: string; score: number | null; cues: ConfidenceCue[]; validation_warnings: ConfidenceCueValidationWarning[]; rationale: string; }
export interface Claim {
  claim_id: string; medication_name: string; status?: string; dose_value?: number; dose_unit?: string;
  frequency?: string; route?: string; negated: boolean; negation_span?: Span; adherence_gap: boolean; adherence_span?: Span; supporting_spans: Span[]; confidence: Confidence;
}
export interface Evidence { evidence_id: string; medication_name: string; resource_type: string; resource_id?: string; source_path: string; status?: string; dose_value?: number; dose_unit?: string; dose_values: number[]; dose_units: string[]; frequency?: string; raw_text: string; }
export interface FieldComparison { field: string; relation: Relation; claim_value: string | number | null; record_values: Array<string | number>; evidence_ids: string[]; rationale: string; }
export interface Divergence { claim_id: string; relation: Relation; divergence_score: number | null; disputed_fields: string[]; rationale: string; supporting_evidence_ids: string[]; conflicting_evidence_ids: string[]; field_comparisons: FieldComparison[]; }
export interface Resolution { claim_id: string; resolved: boolean; resolution_type?: string; resolving_claim_id?: string; resolution_span?: Span; resolved_value?: string; disputed_fields: string[]; resolved_fields: string[]; unresolved_fields: string[]; chart_conflict_remaining: boolean; rationale: string; }
export interface Action { claim_id: string; route: Route; ced_score: number | null; rank: number | null; recommended_action: string; routing_rationale: string; claim: Claim; divergence: Divergence; resolution: Resolution; }
export interface Analysis {
  encounter_id: string; summary: { claims: number; patient_clarifications: number; chart_cleanup: number; clinician_review: number; no_action: number; };
  turns: Turn[]; claims: Claim[]; record_evidence: Evidence[]; actions: Action[];
  ced_results: Record<string, { confidence_score: number | null; divergence_score: number | null; ced_score: number | null; scorable: boolean; abstention_reason?: string; formula_version: string; }>;
}
