import type { Claim } from "../api/types";
export function Provenance({ claim }: { claim: Claim }) {
  return <p className="provenance">Transcript: {claim.supporting_spans.map(span => `${span.start_char}:${span.end_char}`).join(", ")}</p>;
}
