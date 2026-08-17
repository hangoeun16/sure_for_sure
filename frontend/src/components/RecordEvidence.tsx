import type { Evidence } from "../api/types";
export function RecordEvidence({ items }: { items: Evidence[] }) {
  return <div className="evidence"><details><summary>Linked record evidence ({items.length})</summary>{items.length ? items.map(item => <p key={item.evidence_id}><strong>{item.raw_text || item.medication_name}</strong><br /><span className="provenance">{item.resource_type}/{item.resource_id ?? "derived"} · {item.source_path}</span></p>) : <p>No linked record evidence.</p>}</details></div>;
}
