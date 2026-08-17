import type { Analysis } from "../api/types";
import { ActionCard } from "./ActionCard";
import { ActionSummary } from "./ActionSummary";
export function ReviewPanel({ analysis }: { analysis: Analysis }) {
  return <section className="panel"><div className="panel-heading"><h2>Review queue</h2><span className="technical">CED-ranked</span></div><div className="panel-body"><ActionSummary summary={analysis.summary} /><div className="action-list">{analysis.actions.map(action => <ActionCard key={action.claim_id} action={action} ced={analysis.ced_results[action.claim_id]} evidence={analysis.record_evidence} />)}</div></div></section>;
}
