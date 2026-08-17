import type { Resolution } from "../api/types";
export function ResolutionNotice({ resolution }: { resolution: Resolution }) {
  if (!resolution.disputed_fields.length) return null;
  const heading = resolution.resolved ? "✓ Resolved later in dialogue" : "Unresolved discrepancy";
  return <div className="resolution"><strong>{heading}</strong><br />Disputed: {resolution.disputed_fields.join(", ")}. {resolution.resolved_fields.length > 0 && <>Established later: {resolution.resolved_fields.join(", ")}. </>}{resolution.unresolved_fields.length > 0 && <>Still unresolved: {resolution.unresolved_fields.join(", ")}. </>}{resolution.chart_conflict_remaining && "Chart cleanup remains. "}{resolution.rationale}</div>;
}
