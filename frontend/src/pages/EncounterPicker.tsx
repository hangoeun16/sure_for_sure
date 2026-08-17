import type { EncounterListItem } from "../api/types";
import { EncounterCard } from "../components/EncounterCard";
export function EncounterPicker({ encounters, onOpen }: { encounters: EncounterListItem[]; onOpen: (id: string) => void }) {
  return <main className="shell"><div className="hero"><div><span className="eyebrow">Clinician worklist</span><h1>Medication claims,<br />made inspectable.</h1><p>CED prioritizes strongly expressed patient claims that diverge from the available record. It is an attention heuristic—not a clinical risk score.</p></div></div><div className="encounter-grid">{encounters.map(item => <EncounterCard key={item.id} encounter={item} onOpen={() => onOpen(item.id)} />)}</div></main>;
}
