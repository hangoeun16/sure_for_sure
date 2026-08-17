"""
adapter.py — bridge single-encounter engine output -> a trajectory event,
and provide a helper to build the same event shape from extract_events output.

Two producers converge on ONE event schema (matching trajectory.TrajectoryState):
  V1  : single-encounter engine (res0216_end2end) candidates  -> encounter_to_event()
  V2+ : extract_events longitudinal extraction (dict)          -> extracted_to_event()

This is the missing seam the feedback flagged: RES0216 -> encounter event ->
trajectory node, in the same shape the follow-ups already use.
"""

from trajectory import TrajectoryState, EvidenceItem, Commitment

# consequence ordering for picking the encounter's representative action
ACTION_ORDER = {"none": 0, "planned": 1, "resumed": 1, "self_reduced": 2, "discontinued": 3}
EVIDENCE_ORDER = {"support": 0, "silent": 1, "not_assessable": 1,
                  "source_conflict": 2, "contradict": 3}


def _infer_action_from_claim(claim_text: str) -> str:
    """DEMO heuristic — keyword match, NOT a general clinical parser.

    This maps the authored V1 candidate phrasings to an action. It is deliberately
    shallow: e.g. "twice daily" -> resumed would misfire on "prescribed twice daily
    but never resumed it." The real meaning-extraction path (dialogue -> state) is
    the LLM step in extract_events.py; this function only handles the fixed V1
    candidate format. Don't present it as generalizable extraction.
    """
    t = claim_text.lower()
    if any(k in t for k in ("stopped", "discontinu", "no longer", "quit")):
        return "discontinued"
    if any(k in t for k in ("once daily", "morning only", "reduc", "skip", "cut", "just in the morning")):
        return "self_reduced"
    if any(k in t for k in ("resume", "twice daily", "back to")):
        return "resumed"
    return "none"


def encounter_to_event(topic_id, encounter_id, candidates, record_meta=None,
                       clinician_response="elicited_rationale",
                       resolution="partially_addressed"):
    """candidates: list of dicts from the single-encounter engine, each
       {claim, evidence, grade, cues:[(type,token)], target}.
       Collapses same-topic candidates into ONE encounter event."""
    if not candidates:
        return None

    # representative action = most consequential inferred action across candidates
    action = "none"
    for c in candidates:
        a = _infer_action_from_claim(c["claim"])
        if ACTION_ORDER.get(a, 0) > ACTION_ORDER.get(action, 0):
            action = a

    # evidence: strongest relation drives; carry the prescription contradiction
    evidence = []
    strongest = max(candidates, key=lambda c: EVIDENCE_ORDER.get(c["evidence"], 0))
    if strongest["evidence"] == "contradict":
        # use a real prescription date if the record carries one; otherwise leave
        # it undated. Don't fabricate a date — evidence_relation() already treats
        # an undated structured field as older, which is what a standing
        # prescription is relative to the patient's current report.
        ts = (record_meta or {}).get("controller", {}).get("prescribed_date", "") \
             if record_meta else ""
        if record_meta and record_meta.get("controller"):
            evidence.append(EvidenceItem("contradict",
                "prescribed BID vs reported once-daily use / refill history",
                "MedicationRequest", ts))
    # commitments: per-claim, from each candidate's certainty grade + cue
    commitments = []
    for c in candidates:
        cue = c["cues"][0][1] if c.get("cues") else None
        commitments.append(Commitment(target=_claim_scope(c["claim"]),
                                       level=_grade_to_level(c.get("grade")),
                                       cue=cue))

    return TrajectoryState(
        topic_id=topic_id, encounter_id=encounter_id,
        regimen_reported="QD" if action == "self_reduced" else
                         ("none" if action == "discontinued" else "unknown"),
        assessment="reduced regimen reported/assessed as sufficient",
        action=action,
        commitments=commitments,
        evidence=evidence,
        clinician_response=clinician_response,
        resolution=resolution,
    )


def extracted_to_event(topic_id, encounter_id, extracted, resolution=None):
    """extracted: dict from extract_events.py. Build the same TrajectoryState."""
    ev = []
    for e in extracted.get("evidence", []):
        st = (e.get("source_type") or "").lower()
        if "self" in st or "patient" in st:
            continue
        ev.append(EvidenceItem(e.get("relation", "silent"),
                               e.get("assertion", ""),
                               e.get("source_type", "record"),
                               e.get("timestamp") or ""))   # undated stays undated;
                                                            # evidence_relation() treats
                                                            # an undated field as older.
    commitments = [Commitment(c.get("target", "claim"),
                              c.get("level", "not_asserted"),
                              c.get("cue"))
                   for c in extracted.get("commitments", [])]
    return TrajectoryState(
        topic_id=topic_id, encounter_id=encounter_id,
        regimen_reported=extracted.get("patient_regimen_reported", "unknown"),
        assessment="",
        action=extracted.get("action", "none"),
        commitments=commitments,
        evidence=ev,
        clinician_response="extracted",
        resolution=resolution or extracted.get("resolution", "unaddressed"),
        clinical_course=extracted.get("clinical_course", ""),
    )


def _grade_to_level(grade):
    return {"absolute": "emphatic", "high": "emphatic",
            "moderate": "neutral", "low": "hedged",
            "uncertain": "hedged", "unmarked": "not_asserted"}.get(grade, "not_asserted")

def _claim_scope(claim_text):
    t = claim_text.lower()
    if "adherent" in t: return "full_adherence"
    if "sufficient" in t or "no problem" in t: return "QD_sufficiency"
    if "once daily" in t or "morning only" in t: return "daily_use"
    return "regimen"
