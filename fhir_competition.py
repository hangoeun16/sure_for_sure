"""
fhir_competition.py — parse the HACKATHON dataset's FHIR into engine input.

Unlike fhir_record.py (Synthea inhalers, dosing absent → refill inference), the
competition data carries explicit dosageInstruction AND full related_resources.
So here we read dosing directly and detect *duplicate / stale* medication entries
(two statins, two metoprolol doses) — the real source_conflict in patient #10.

Output: a TrajectoryState the refactored engine (trajectory.py) consumes directly,
so nothing downstream changes. This is the "competition data actually runs" proof.
"""
import json
from collections import defaultdict

from trajectory import TrajectoryState, Commitment
from evidence import EvidenceItem

# drug-class grouping: two entries in the same class = a duplicate to reconcile
DRUG_CLASS = {
    "statin":     ("simvastatin", "atorvastatin", "rosuvastatin", "pravastatin"),
    "metoprolol": ("metoprolol",),   # same drug, different strengths = stale dose
}


def _med_text(mr):
    return (mr.get("medicationCodeableConcept", {}).get("text", "")).lower()


def _dose_freq(mr):
    """Read prescribed frequency straight from FHIR (competition data has it)."""
    for di in mr.get("dosageInstruction", []):
        rep = di.get("timing", {}).get("repeat", {})
        if "frequency" in rep and "period" in rep:
            return rep["frequency"] / rep["period"]      # e.g. 1/1 = once daily
    return None


def load_encounter(jsonl_path, index):
    line = open(jsonl_path).readlines()[index]
    return json.loads(line)


def build_states(record):
    """Detect duplicate-class medications -> one TrajectoryState per conflict.

    The duplicates live in the patient's LONGITUDINAL medication list (stale
    entries never removed from the active chart), not in this single encounter's
    new orders. That's the real shape of the #10 conflict: an old simvastatin and
    an old metoprolol 50mg still sitting on the active list years later.
    """
    labels = record["patient_context"]["longitudinal_summary"].get("medication_labels", [])

    # bucket the active medication list by drug class
    by_class = defaultdict(list)
    for name in labels:
        low = name.lower()
        for cls, keys in DRUG_CLASS.items():
            if any(k in low for k in keys):
                by_class[cls].append(name)

    states = []
    for cls, names in by_class.items():
        names = sorted(set(names))
        if len(names) < 2:
            continue   # no duplicate → no conflict

        # Two active entries for the same drug class = a record-internal conflict
        # we CANNOT adjudicate from the record: nothing tells us which is current.
        # So both entries are marked not_assessable — we invent no date and declare
        # neither stale. evidence_relation() reads coexisting not_assessable entries
        # as source_conflict. Which one is current is the clinician's call.
        evidence = [
            EvidenceItem("not_assessable", n, "medication_list", "")
            for n in names
        ]
        states.append(TrajectoryState(
            topic_id=f"med-{cls}", encounter_id=record["metadata"].get("visit_title","")[:24],
            regimen_reported=names[-1], assessment=f"two {cls} entries on the active list",
            action="none",
            commitments=[Commitment("regimen", "neutral")],
            evidence=evidence,
            clinician_response="reconcile", resolution="unaddressed",
            clinical_course=f"{len(names)} {cls} entries active: {', '.join(names)}",
            domain="medication"))
    return states


if __name__ == "__main__":
    import sys
    from trajectory import priority_tier, surface_question
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "data/synthetic-ambient-fhir-25.jsonl"
    idx = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    rec = load_encounter(path, idx)
    print(f"=== competition #{idx}: {rec['metadata']['visit_title']} ===\n")
    states = build_states(rec)
    if not states:
        print("no duplicate-class conflict detected.")
    for s in states:
        div = s.divergence()
        print(f"[{s.topic_id}] {s.clinical_course}")
        print(f"  evidence_relation : {s.evidence_relation()}")
        print(f"  divergence        : {div[0]}  ({div[1]})")
        print(f"  tier              : {priority_tier(s)}")
        print(f"  disposition       : {s.disposition()}")
        print(f"  -> {surface_question(s)}\n")
