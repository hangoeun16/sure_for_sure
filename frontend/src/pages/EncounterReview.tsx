import type { Analysis } from "../api/types";
import { EncounterHeader } from "../components/EncounterHeader";
import { ReviewPanel } from "../components/ReviewPanel";
import { TranscriptPanel } from "../components/TranscriptPanel";
import { ViewToggle } from "../components/ViewToggle";
export function EncounterReview({ analysis, onBack }: { analysis: Analysis; onBack: () => void }) {
  return <main className="shell"><EncounterHeader id={analysis.encounter_id} onBack={onBack} /><ViewToggle /><div className="review-grid"><TranscriptPanel turns={analysis.turns} claims={analysis.claims} /><ReviewPanel analysis={analysis} /></div></main>;
}
