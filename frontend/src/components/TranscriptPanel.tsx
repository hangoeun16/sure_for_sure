import type { Claim, Turn } from "../api/types";
import { DialogueTurn } from "./DialogueTurn";
export function TranscriptPanel({ turns, claims }: { turns: Turn[]; claims: Claim[] }) {
  const highlights = claims.flatMap(claim => claim.supporting_spans);
  return <section className="panel"><div className="panel-heading"><h2>Visit transcript</h2><span className="technical">Exact spans</span></div><div className="panel-body">{turns.map(turn => <DialogueTurn key={turn.index} turn={turn} highlights={highlights} />)}</div></section>;
}
