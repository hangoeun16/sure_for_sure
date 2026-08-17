import type { ClaimReview, MissedReview, PredictionItem, MissedCandidate, ReviewBootstrap, ReviewProgress, TranscriptResponse } from "./types";

const base = import.meta.env.VITE_API_BASE ?? "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${base}/human-review${path}`, {
    headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) },
    ...options,
  });
  if (!response.ok) throw new Error((await response.text()) || `Request failed (${response.status})`);
  return response.json() as Promise<T>;
}

export const reviewApi = {
  bootstrap: () => request<ReviewBootstrap>("/bootstrap"),
  predictions: () => request<PredictionItem[]>("/predictions"),
  missed: () => request<MissedCandidate[]>("/missed-candidates"),
  transcript: (recordId: string) => request<TranscriptResponse>(`/transcripts/${encodeURIComponent(recordId)}`),
  savePrediction: (claimId: string, patch: Partial<ClaimReview>) => request<ClaimReview>(`/predictions/${encodeURIComponent(claimId)}`, { method: "PATCH", body: JSON.stringify(patch) }),
  saveMissed: (candidateId: string, patch: Partial<MissedReview>) => request<MissedReview>(`/missed-candidates/${encodeURIComponent(candidateId)}`, { method: "PATCH", body: JSON.stringify(patch) }),
  progress: () => request<ReviewProgress>("/progress"),
  saveProgress: (queue: "predictions" | "missed", itemId: string) => request<ReviewProgress>("/progress", { method: "PATCH", body: JSON.stringify({ queue, item_id: itemId }) }),
  finalize: () => request<{ review_status: string; reference_claims: number; reference_path: string }>("/finalize", { method: "POST" }),
};
