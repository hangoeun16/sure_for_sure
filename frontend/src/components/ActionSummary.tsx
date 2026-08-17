import type { Analysis } from "../api/types";
export function ActionSummary({ summary }: { summary: Analysis["summary"] }) {
  return <div className="summary-pills"><span className="pill">{summary.claims} claims</span><span className="pill">{summary.patient_clarifications} clarify</span><span className="pill">{summary.chart_cleanup} chart cleanup</span><span className="pill">{summary.clinician_review} review</span></div>;
}
