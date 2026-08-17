import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { reviewApi } from "./api";
import type {
  ClaimAssessment,
  ClaimReview,
  CueAssessment,
  DerivedAssessment,
  FieldAssessment,
  HallucinationAssessment,
  MissedAssessment,
  MissedCandidate,
  MissedReview,
  PredictionItem,
  QuoteAssessment,
  ReviewBootstrap,
  ReviewProgress,
  TranscriptResponse,
} from "./types";
import "./review.css";

const reviewFields = [
  ["medication_identity", "Medication identity"],
  ["dose_value", "Dose value"],
  ["dose_unit", "Dose unit"],
  ["frequency", "Frequency"],
  ["route", "Route"],
  ["status_adherence", "Status / adherence"],
  ["negation", "Negation"],
] as const;

const claimOptions: Array<[ClaimAssessment, string]> = [
  ["correct_claim", "Correct claim"],
  ["not_medication_claim", "Not a medication claim"],
  ["ambiguous", "Ambiguous"],
  ["needs_domain_review", "Needs domain review"],
];
const quoteOptions: Array<[QuoteAssessment, string]> = [["correct", "Correct"], ["incorrect", "Incorrect"], ["ambiguous", "Ambiguous"]];
const fieldOptions: Array<[FieldAssessment, string]> = [["correct", "Correct"], ["incorrect", "Incorrect"], ["not_stated_by_patient", "Not stated"], ["ambiguous", "Ambiguous"], ["needs_domain_review", "Domain review"]];
const cueOptions: Array<[CueAssessment, string]> = [["correct", "Correct"], ["incorrect", "Incorrect"], ["no_cue_should_be_present", "No cue should be present"], ["ambiguous", "Ambiguous"]];
const derivedOptions: Array<[DerivedAssessment, string]> = [["correct_by_rubric", "Correct by rubric"], ["incorrect_by_rubric", "Incorrect by rubric"], ["ambiguous", "Ambiguous"]];
const hallucinationOptions: Array<[HallucinationAssessment, string]> = [["no", "No"], ["yes", "Yes"], ["ambiguous", "Ambiguous"]];
const missedOptions: Array<[MissedAssessment, string]> = [["already_covered", "Yes / already covered"], ["likely_missed_medication_claim", "No — likely missed claim"], ["not_medication_claim", "Not a medication claim"], ["ambiguous", "Ambiguous"], ["needs_domain_review", "Needs domain review"]];

type Queue = "predictions" | "missed";
type Filter = "all" | "unreviewed" | "flagged";

function ChoiceGroup<T extends string>({ label, value, options, onChange }: { label: string; value?: T; options: Array<[T, string]>; onChange: (value: T) => void }) {
  return <fieldset className="choice-group"><legend>{label}</legend><div className="choice-row">{options.map(([key, text]) => <label key={key} className={value === key ? "choice selected" : "choice"}><input type="radio" checked={value === key} onChange={() => onChange(key)} />{text}</label>)}</div></fieldset>;
}

function Value({ children }: { children: ReactNode }) {
  return <span className="prediction-value">{children ?? "—"}</span>;
}

function predictionComplete(review?: ClaimReview) {
  if (!review?.claim_assessment) return false;
  if (review.claim_assessment !== "correct_claim") return true;
  return Boolean(review.supporting_quote && review.confidence_cues && review.derived_confidence && review.hallucination && review.field_reviews && reviewFields.every(([field]) => review.field_reviews?.[field]));
}

function missedComplete(review?: MissedReview) {
  if (!review?.decision) return false;
  return review.decision !== "likely_missed_medication_claim" || Boolean(review.supporting_quote?.trim());
}

function flagged(review?: ClaimReview | MissedReview) {
  return JSON.stringify(review ?? {}).includes("ambiguous") || JSON.stringify(review ?? {}).includes("needs_domain_review");
}

function HighlightedTurn({ item, turn }: { item: PredictionItem; turn: PredictionItem["context_turns"][number] }) {
  const spans = item.claim.supporting_spans.filter(span => span.turn_index === turn.index).sort((a, b) => a.start_char - b.start_char);
  if (!spans.length) return <p>{turn.text}</p>;
  const pieces: ReactNode[] = [];
  let cursor = 0;
  spans.forEach((span, index) => {
    const start = Math.max(0, span.start_char - turn.start_char);
    const end = Math.max(start, span.end_char - turn.start_char);
    pieces.push(turn.text.slice(cursor, start));
    pieces.push(<mark key={`${span.start_char}-${index}`}>{turn.text.slice(start, end)}</mark>);
    cursor = end;
  });
  pieces.push(turn.text.slice(cursor));
  return <p>{pieces}</p>;
}

function Guide() {
  return <details className="review-guide"><summary>Review guide and confidence rubric</summary><div><p><strong>Review only what the patient actually said.</strong> Do not use medical knowledge to fill missing information. If the patient did not name a drug, do not infer it from the chart. If a decision requires clinical knowledge, choose “Needs domain review.” Confidence refers only to expressed linguistic certainty, not how medically plausible or detailed the claim is.</p><div className="guide-grid"><div><b>Hedge</b><span>maybe, I think, I guess, not sure, could be, probably</span></div><div><b>Booster</b><span>definitely, for sure, I know</span></div><div><b>Hesitation</b><span>... or …; neutral without a hedge</span></div><div><b>Not confidence</b><span>daily, every day, still</span></div></div><ul><li>“I think I take 50 mg.” → hedge</li><li>“I definitely take 50 mg.” → booster</li><li>“I take 50 mg every day.” → neutral</li><li>“I take... 50 mg.” → hesitation, but neutral without another hedge</li><li>“I take something for migraines.” → identity unspecified; not automatically hedged</li></ul></div></details>;
}

export function HumanReviewApp() {
  const [bootstrap, setBootstrap] = useState<ReviewBootstrap | null>(null);
  const [predictions, setPredictions] = useState<PredictionItem[]>([]);
  const [missed, setMissed] = useState<MissedCandidate[]>([]);
  const [queue, setQueue] = useState<Queue>("predictions");
  const [currentId, setCurrentId] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [encounter, setEncounter] = useState("all");
  const [progress, setProgress] = useState<ReviewProgress | null>(null);
  const [saveState, setSaveState] = useState("Saved locally");
  const [error, setError] = useState("");
  const [transcript, setTranscript] = useState<TranscriptResponse | null>(null);
  const [finalMessage, setFinalMessage] = useState("");

  useEffect(() => {
    Promise.all([reviewApi.bootstrap(), reviewApi.predictions(), reviewApi.missed()]).then(([boot, predictionItems, missedItems]) => {
      setBootstrap(boot); setPredictions(predictionItems); setMissed(missedItems); setProgress(boot.progress);
      const resumeQueue = boot.progress.last_queue;
      const fallback = resumeQueue === "predictions" ? predictionItems[0]?.claim_id : missedItems[0]?.candidate_id;
      setQueue(resumeQueue); setCurrentId(boot.progress.last_item_id || fallback || "");
    }).catch(reason => setError(String(reason)));
  }, []);

  const items = useMemo(() => {
    const source = queue === "predictions" ? predictions : missed;
    return source.filter(item => {
      if (encounter !== "all" && String(item.record_index) !== encounter) return false;
      const complete = queue === "predictions" ? predictionComplete((item as PredictionItem).review) : missedComplete((item as MissedCandidate).review);
      if (filter === "unreviewed" && complete) return false;
      if (filter === "flagged" && !flagged(item.review)) return false;
      return true;
    });
  }, [queue, predictions, missed, encounter, filter]);

  useEffect(() => {
    if (items.length && !items.some(item => (queue === "predictions" ? (item as PredictionItem).claim_id : (item as MissedCandidate).candidate_id) === currentId)) {
      setCurrentId(queue === "predictions" ? (items[0] as PredictionItem).claim_id : (items[0] as MissedCandidate).candidate_id);
    }
  }, [items, currentId, queue]);

  const currentIndex = Math.max(0, items.findIndex(item => (queue === "predictions" ? (item as PredictionItem).claim_id : (item as MissedCandidate).candidate_id) === currentId));
  const current = items[currentIndex];

  const refreshProgress = useCallback(() => reviewApi.progress().then(setProgress), []);
  const selectItem = useCallback((nextQueue: Queue, id: string) => {
    setQueue(nextQueue); setCurrentId(id); setTranscript(null); reviewApi.saveProgress(nextQueue, id).then(setProgress).catch(reason => setError(String(reason)));
  }, []);
  const move = useCallback((delta: number) => {
    if (!items.length) return;
    const next = items[Math.min(items.length - 1, Math.max(0, currentIndex + delta))];
    const id = queue === "predictions" ? (next as PredictionItem).claim_id : (next as MissedCandidate).candidate_id;
    selectItem(queue, id);
  }, [items, currentIndex, queue, selectItem]);

  const savePrediction = useCallback((item: PredictionItem, patch: Partial<ClaimReview>) => {
    const merged = { ...(item.review ?? {}), ...patch } as ClaimReview;
    setPredictions(currentItems => currentItems.map(candidate => candidate.claim_id === item.claim_id ? { ...candidate, review: merged } : candidate));
    setSaveState("Saving…");
    reviewApi.savePrediction(item.claim_id, patch).then(saved => {
      setPredictions(currentItems => currentItems.map(candidate => candidate.claim_id === item.claim_id ? { ...candidate, review: saved } : candidate));
      setSaveState("Saved locally"); return refreshProgress();
    }).catch(reason => { setSaveState("Save failed"); setError(String(reason)); });
  }, [refreshProgress]);

  const saveMissed = useCallback((item: MissedCandidate, patch: Partial<MissedReview>) => {
    const merged = { ...(item.review ?? {}), ...patch } as MissedReview;
    setMissed(currentItems => currentItems.map(candidate => candidate.candidate_id === item.candidate_id ? { ...candidate, review: merged } : candidate));
    setSaveState("Saving…");
    reviewApi.saveMissed(item.candidate_id, patch).then(saved => {
      setMissed(currentItems => currentItems.map(candidate => candidate.candidate_id === item.candidate_id ? { ...candidate, review: saved } : candidate));
      setSaveState("Saved locally"); return refreshProgress();
    }).catch(reason => { setSaveState("Save failed"); setError(String(reason)); });
  }, [refreshProgress]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (["INPUT", "TEXTAREA", "SELECT"].includes((event.target as HTMLElement).tagName)) return;
      if (event.key === "ArrowRight" || event.key.toLowerCase() === "j") move(1);
      if (event.key === "ArrowLeft" || event.key.toLowerCase() === "k") move(-1);
      if (event.key.toLowerCase() === "u") setFilter("unreviewed");
      if (event.key.toLowerCase() === "a") setFilter("flagged");
      if (/^[1-4]$/.test(event.key) && current && queue === "predictions") savePrediction(current as PredictionItem, { claim_assessment: claimOptions[Number(event.key) - 1][0] });
      if (/^[1-5]$/.test(event.key) && current && queue === "missed") saveMissed(current as MissedCandidate, { decision: missedOptions[Number(event.key) - 1][0] });
    };
    window.addEventListener("keydown", handler); return () => window.removeEventListener("keydown", handler);
  }, [current, queue, move, savePrediction, saveMissed]);

  if (error && !bootstrap) return <main className="review-shell"><div className="review-error">{error}</div></main>;
  if (!bootstrap) return <main className="review-shell"><p>Loading frozen review queue…</p></main>;

  const encounterOptions = Array.from(new Set((queue === "predictions" ? predictions : missed).map(item => item.record_index))).sort((a, b) => a - b);
  return <div className="human-review-app"><header className="review-topbar"><div><span className="review-kicker">Transcript-only evaluation</span><h1>Human review workspace</h1></div><div className="save-status"><span className="save-dot" />{saveState}</div></header><main className="review-shell">
    <section className="scope-banner"><strong>Non-clinical scope.</strong> Judge extraction fidelity from patient speech only. Do not evaluate treatment, chart correctness, CED, routing, or clinical action.<span>{bootstrap.manifest.model} · {bootstrap.manifest.prompt_version}</span></section>
    <Guide />
    {error && <div className="review-error"><button onClick={() => setError("")}>×</button>{error}</div>}
    <nav className="review-toolbar">
      <div className="queue-tabs"><button className={queue === "predictions" ? "active" : ""} onClick={() => { const id = predictions[0]?.claim_id; if (id) selectItem("predictions", id); }}>A. Prediction review <span>{progress?.predictions.complete}/{progress?.predictions.total}</span></button><button className={queue === "missed" ? "active" : ""} onClick={() => { const id = missed[0]?.candidate_id; if (id) selectItem("missed", id); }}>B. Missed-claim discovery <span>{progress?.missed_candidates.complete}/{progress?.missed_candidates.total}</span></button></div>
      <div className="filters"><select aria-label="Review filter" value={filter} onChange={event => setFilter(event.target.value as Filter)}><option value="all">All items</option><option value="unreviewed">Unreviewed</option><option value="flagged">Ambiguous / domain review</option></select><select aria-label="Jump by encounter" value={encounter} onChange={event => setEncounter(event.target.value)}><option value="all">All encounters</option>{encounterOptions.map(index => <option key={index} value={index}>Encounter {index + 1}</option>)}</select></div>
    </nav>
    {current ? <><div className="review-position"><span>{queue === "predictions" ? "Prediction" : "Candidate"} {currentIndex + 1} / {items.length}{filter !== "all" ? ` (${filter} filter)` : ""}</span><span>Encounter {current.encounter_number} / {current.encounter_count} · <code>{current.record_id}</code></span></div>{queue === "predictions" ? <PredictionReview item={current as PredictionItem} save={savePrediction} transcript={transcript} loadTranscript={() => reviewApi.transcript(current.record_id).then(setTranscript)} /> : <MissedReviewPanel item={current as MissedCandidate} save={saveMissed} />}
      <footer className="review-nav"><button onClick={() => move(-1)} disabled={currentIndex === 0}>← Previous <kbd>K</kbd></button><span>{predictionComplete((current as PredictionItem).review) || missedComplete((current as MissedCandidate).review) ? "Complete" : "In progress"}</span><button onClick={() => move(1)} disabled={currentIndex >= items.length - 1}>Next <kbd>J</kbd> →</button></footer></> : <div className="empty-state">No items match this filter.</div>}
    <section className="completion-panel"><div><strong>Review completion</strong><p>{progress?.predictions.complete}/{progress?.predictions.total} predictions · {progress?.missed_candidates.complete}/{progress?.missed_candidates.total} recall candidates</p></div><button disabled={!progress?.all_complete} onClick={() => reviewApi.finalize().then(result => setFinalMessage(`Reference set written: ${result.reference_claims} claims`)).catch(reason => setError(String(reason)))}>Finalize human reference set</button>{finalMessage && <p className="final-message">{finalMessage}</p>}</section>
    <p className="shortcut-help"><kbd>J</kbd>/<kbd>→</kbd> next · <kbd>K</kbd>/<kbd>←</kbd> previous · <kbd>U</kbd> unreviewed · <kbd>A</kbd> flagged · number keys choose the primary decision</p>
  </main></div>;
}

function PredictionReview({ item, save, transcript, loadTranscript }: { item: PredictionItem; save: (item: PredictionItem, patch: Partial<ClaimReview>) => void; transcript: TranscriptResponse | null; loadTranscript: () => void }) {
  const review = item.review ?? {} as ClaimReview;
  const claim = item.claim;
  const confidence = claim.confidence;
  const updateField = (field: string, value: FieldAssessment) => save(item, { field_reviews: { ...(review.field_reviews ?? {}), [field]: value } });
  return <div className="annotation-grid"><section className="transcript-card"><div className="card-heading"><div><span className="review-kicker">Encounter context</span><h2>Patient evidence</h2></div><button className="text-button" onClick={loadTranscript}>{transcript?.record_id === item.record_id ? "Refresh" : "Show full transcript"}</button></div><div className="context-turns">{item.context_turns.map(turn => <div key={turn.index} className={item.supporting_turn_indexes.includes(turn.index) ? "context-turn supporting" : "context-turn"}><span>{turn.speaker}</span><HighlightedTurn item={item} turn={turn} /></div>)}</div>{transcript?.record_id === item.record_id && <details open className="full-transcript"><summary>Full transcript</summary>{transcript.turns.map(turn => <div key={turn.index} className="context-turn"><span>{turn.speaker}</span><p>{turn.text}</p></div>)}</details>}</section>
    <section className="prediction-card"><div className="prediction-label">CLAUDE PREDICTION</div><dl className="prediction-list"><div><dt>Medication</dt><dd><Value>{claim.medication_name}</Value></dd></div><div><dt>Dose</dt><dd><Value>{claim.dose_value ?? "—"}</Value></dd></div><div><dt>Unit</dt><dd><Value>{claim.dose_unit ?? "—"}</Value></dd></div><div><dt>Frequency</dt><dd><Value>{claim.frequency ?? "—"}</Value></dd></div><div><dt>Route</dt><dd><Value>{claim.route ?? "—"}</Value></dd></div><div><dt>Status / adherence</dt><dd><Value>{`${claim.status ?? "—"}${claim.adherence_gap ? " · adherence gap" : ""}`}</Value></dd></div><div><dt>Negation</dt><dd><Value>{claim.negated ? "Negated" : "Not negated"}</Value></dd></div><div><dt>Confidence cues</dt><dd><Value>{confidence.cues.length ? confidence.cues.map(cue => `${cue.type}: “${cue.span.text}”`).join(" · ") : "None"}</Value></dd></div><div><dt>Derived confidence</dt><dd><Value>{confidence.level}</Value></dd></div><div className="wide"><dt>Supporting quote</dt><dd><Value>{claim.supporting_spans.map(span => `“${span.text}”`).join(" · ")}</Value></dd></div></dl></section>
    <section className="decision-card"><span className="review-kicker">Human review</span><h2>Transcript-observable checks</h2><ChoiceGroup label="A. Is this a real patient medication claim?" value={review.claim_assessment} options={claimOptions} onChange={value => save(item, { claim_assessment: value })} /><ChoiceGroup label="B. Supporting quote" value={review.supporting_quote} options={quoteOptions} onChange={value => save(item, { supporting_quote: value })} /><div className="field-review"><h3>C. Structured fields</h3>{reviewFields.map(([field, label]) => <ChoiceGroup key={field} label={label} value={review.field_reviews?.[field]} options={fieldOptions} onChange={value => updateField(field, value)} />)}</div><ChoiceGroup label="D. Confidence cues" value={review.confidence_cues} options={cueOptions} onChange={value => save(item, { confidence_cues: value })} /><ChoiceGroup label={`E. Derived confidence: ${confidence.level}`} value={review.derived_confidence} options={derivedOptions} onChange={value => save(item, { derived_confidence: value })} /><ChoiceGroup label="F. Did Claude add information not stated by the patient?" value={review.hallucination} options={hallucinationOptions} onChange={value => save(item, { hallucination: value })} />{review.hallucination === "yes" && <label className="notes-label">Unsupported information (optional)<textarea defaultValue={review.hallucination_notes ?? ""} onBlur={event => save(item, { hallucination_notes: event.target.value })} /></label>}<label className="notes-label">Reviewer notes (optional)<textarea defaultValue={review.notes ?? ""} onBlur={event => save(item, { notes: event.target.value })} /></label></section></div>;
}

function MissedReviewPanel({ item, save }: { item: MissedCandidate; save: (item: MissedCandidate, patch: Partial<MissedReview>) => void }) {
  const review = item.review ?? {} as MissedReview;
  const useSelection = () => { const selection = window.getSelection()?.toString().trim() ?? ""; if (selection && item.turn.text.includes(selection)) save(item, { supporting_quote: selection }); };
  return <div className="missed-grid"><section className="transcript-card recall-card"><div className="card-heading"><div><span className="review-kicker">Patient-only recall candidate</span><h2>Possible missed claim</h2></div></div><div className="bias-shield">Claude’s structured predictions are intentionally hidden in this queue.</div><blockquote id={`turn-${item.candidate_id}`}>{item.turn.text}</blockquote><div className="signal-list"><span>Transparent lexical signals</span>{item.signals.map(signal => <code key={signal}>{signal}</code>)}</div></section><section className="decision-card"><span className="review-kicker">Human recall review</span><h2>Does this turn contain a missed claim?</h2><ChoiceGroup label="Claude extracted a claim from this statement?" value={review.decision} options={missedOptions} onChange={value => save(item, { decision: value })} />{review.decision === "likely_missed_medication_claim" && <div className="missed-fields"><p>Select exact words in the patient turn and use the selection, or use the full turn. Do not medically normalize the wording.</p><div className="selection-actions"><button onClick={useSelection}>Use selected text</button><button onClick={() => save(item, { supporting_quote: item.turn.text })}>Use full patient turn</button></div><label>Supporting quote<textarea value={review.supporting_quote ?? ""} onChange={event => save(item, { supporting_quote: event.target.value })} /></label><label>Medication name as spoken<input value={review.medication_name_as_spoken ?? ""} placeholder="unspecified" onChange={event => save(item, { medication_name_as_spoken: event.target.value })} /></label><label>Dose as spoken<input value={review.dose_as_spoken ?? ""} placeholder="unspecified" onChange={event => save(item, { dose_as_spoken: event.target.value })} /></label><label>Frequency as spoken<input value={review.frequency_as_spoken ?? ""} placeholder="unspecified" onChange={event => save(item, { frequency_as_spoken: event.target.value })} /></label><label>Status / adherence as spoken<input value={review.status_adherence_as_spoken ?? ""} placeholder="unspecified" onChange={event => save(item, { status_adherence_as_spoken: event.target.value })} /></label><label>Explicit confidence cues<input value={review.confidence_cues_as_spoken ?? ""} placeholder="unspecified" onChange={event => save(item, { confidence_cues_as_spoken: event.target.value })} /></label></div>}<label className="notes-label">Reviewer notes (optional)<textarea defaultValue={review.notes ?? ""} onBlur={event => save(item, { notes: event.target.value })} /></label></section></div>;
}
