import type { Claim, Turn } from "../api/types";

export type ClaimAssessment = "correct_claim" | "not_medication_claim" | "ambiguous" | "needs_domain_review";
export type QuoteAssessment = "correct" | "incorrect" | "ambiguous";
export type FieldAssessment = "correct" | "incorrect" | "not_stated_by_patient" | "ambiguous" | "needs_domain_review";
export type CueAssessment = "correct" | "incorrect" | "no_cue_should_be_present" | "ambiguous";
export type DerivedAssessment = "correct_by_rubric" | "incorrect_by_rubric" | "ambiguous";
export type HallucinationAssessment = "no" | "yes" | "ambiguous";
export type MissedAssessment = "already_covered" | "likely_missed_medication_claim" | "not_medication_claim" | "ambiguous" | "needs_domain_review";

export interface ClaimReview {
  source_run_id: string;
  record_id: string;
  record_index: number;
  claim_id: string;
  claim_assessment?: ClaimAssessment;
  supporting_quote?: QuoteAssessment;
  field_reviews?: Record<string, FieldAssessment>;
  confidence_cues?: CueAssessment;
  derived_confidence?: DerivedAssessment;
  hallucination?: HallucinationAssessment;
  hallucination_notes?: string;
  notes?: string;
  updated_at?: string;
}

export interface MissedReview {
  source_run_id: string;
  record_id: string;
  record_index: number;
  candidate_id: string;
  turn_index: number;
  decision?: MissedAssessment;
  supporting_quote?: string;
  medication_name_as_spoken?: string;
  dose_as_spoken?: string;
  frequency_as_spoken?: string;
  status_adherence_as_spoken?: string;
  confidence_cues_as_spoken?: string;
  notes?: string;
  updated_at?: string;
}

export interface PredictionItem {
  claim_id: string;
  record_id: string;
  record_index: number;
  encounter_number: number;
  encounter_count: number;
  queue_index: number;
  queue_total: number;
  claim: Claim;
  context_turns: Turn[];
  supporting_turn_indexes: number[];
  review?: ClaimReview;
}

export interface MissedCandidate {
  candidate_id: string;
  record_id: string;
  record_index: number;
  encounter_number: number;
  encounter_count: number;
  queue_index: number;
  queue_total: number;
  turn: Turn;
  signals: string[];
  review?: MissedReview;
}

export interface ReviewProgress {
  last_queue: "predictions" | "missed";
  last_item_id: string | null;
  predictions: { complete: number; total: number };
  missed_candidates: { complete: number; total: number };
  all_complete: boolean;
  updated_at: string;
}

export interface ReviewBootstrap {
  manifest: {
    source_run_id: string;
    model: string;
    prompt_version: string;
    prompt_hash: string;
    dataset: string;
    review_scope: string;
    review_status: string;
  };
  progress: ReviewProgress;
  prediction_count: number;
  missed_candidate_count: number;
  workspace: string;
}

export interface TranscriptResponse { record_id: string; record_index: number; turns: Turn[]; }
