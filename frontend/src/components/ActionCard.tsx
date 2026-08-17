import type { Action, Analysis, Evidence } from "../api/types";
import { CEDBreakdown } from "./CEDBreakdown";
import { Provenance } from "./Provenance";
import { RecordEvidence } from "./RecordEvidence";
import { ResolutionNotice } from "./ResolutionNotice";

export function ActionCard({ action, ced, evidence }: { action: Action; ced: Analysis["ced_results"][string]; evidence: Evidence[] }) {
  const linked = evidence.filter(item => [...action.divergence.supporting_evidence_ids, ...action.divergence.conflicting_evidence_ids].includes(item.evidence_id));
  return <article className={`action-card ${action.route}`}><div className="action-top"><div><span className="eyebrow">{action.rank ? `Rank ${action.rank}` : "Reviewed"}</span><h3>{action.claim.medication_name}</h3></div><span className="route">{action.route.replaceAll("_", " ")}</span></div><p>Patient claim: {action.claim.status ?? "status unstated"}{action.claim.dose_value != null ? ` · ${action.claim.dose_value} ${action.claim.dose_unit ?? ""}` : ""}{action.claim.frequency ? ` · ${action.claim.frequency}` : ""}</p><CEDBreakdown action={action} ced={ced} /><ResolutionNotice resolution={action.resolution} /><p><strong>{action.recommended_action}</strong></p><p>{action.routing_rationale}</p><p>{action.divergence.rationale}</p><RecordEvidence items={linked} /><Provenance claim={action.claim} /></article>;
}
