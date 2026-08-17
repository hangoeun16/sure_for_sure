import type { EncounterListItem } from "../api/types";
export function EncounterCard({ encounter, onOpen }: { encounter: EncounterListItem; onOpen: () => void }) {
  return <button className="encounter-card" onClick={onOpen}><span className="eyebrow">Encounter {encounter.index + 1}</span><h3>{encounter.title}</h3><p>{[encounter.date, encounter.visit_type].filter(Boolean).join(" · ") || "Ready for review"}</p><span className="technical">Open review →</span></button>;
}
