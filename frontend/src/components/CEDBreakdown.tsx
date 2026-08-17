import type { Action, Analysis } from "../api/types";
export function CEDBreakdown({ action, ced }: { action: Action; ced: Analysis["ced_results"][string] }) {
  const value = (number: number | null) => number === null ? "Abstain" : number.toFixed(2);
  return <div className="ced-grid"><div className="metric"><span className="eyebrow">Confidence</span><strong>{value(ced.confidence_score)}</strong><span>{action.claim.confidence.level}</span></div><span className="operator">×</span><div className="metric"><span className="eyebrow">Record divergence</span><strong>{value(ced.divergence_score)}</strong><span>{action.divergence.relation.replaceAll("_", " ")}</span></div><span className="operator">=</span><div className="metric"><span className="eyebrow">CED</span><strong>{value(ced.ced_score)}</strong><span>{ced.formula_version}</span></div></div>;
}
