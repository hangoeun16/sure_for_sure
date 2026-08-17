import type { Span, Turn } from "../api/types";

export function DialogueTurn({ turn, highlights }: { turn: Turn; highlights: Span[] }) {
  const local = highlights.filter(span => span.turn_index === turn.index).map(span => ({ start: span.start_char - turn.start_char, end: span.end_char - turn.start_char })).sort((a,b) => a.start-b.start);
  const parts: React.ReactNode[] = []; let cursor = 0;
  local.forEach((range, index) => { parts.push(turn.text.slice(cursor, range.start)); parts.push(<mark key={index}>{turn.text.slice(range.start, range.end)}</mark>); cursor = range.end; });
  parts.push(turn.text.slice(cursor));
  return <div className="dialogue"><span className="speaker">{turn.speaker_label}</span><p>{parts}</p></div>;
}
