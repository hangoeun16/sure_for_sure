"""
analyze.py — the analysis core the web app calls.

Takes ONE competition encounter (parsed JSON dict) and runs the REAL engine over
it: builds TrajectoryStates, computes divergence / tier / disposition / question.
Returns plain dicts the frontend renders. No pre-computed data — this is the
pipeline actually running on whatever encounter is fed in.
"""
from fhir_competition import build_states
from trajectory import (TrajectoryState, Commitment, priority_tier,
                        priority_drivers, surface_question)
from evidence import EvidenceItem


def _card(state):
    dtype, ddesc = state.divergence()
    q = surface_question(state)
    disp = state.disposition()
    # map disposition -> UI routing class + label
    route = {"ask_patient": ("ask", "Ask patient"),
             "verify_current_regimen": ("verify", "Verify record"),
             "none": ("suppress", "Suppressed"),
             "monitor": ("ask", "Monitor")}.get(disp, ("ask", disp))
    owner = {"ask": "patient", "verify": "record", "suppress": "—"}[route[0]]
    return {
        "topic": state.topic_id,
        "divergence": dtype or "none",
        "divergence_desc": ddesc,
        "evidence_relation": state.evidence_relation(),
        "tier": priority_tier(state),
        "disposition": disp,
        "route_class": route[0],
        "route_label": route[1],
        "owner": owner,
        "drivers": priority_drivers(state),
        "assessment": state.assessment,
        "clinical_course": state.clinical_course,
        "question": q,
        "surfaced": q is not None,
        "domain": state.domain,
    }


def analyze_encounter(record: dict) -> dict:
    """Run the engine on one competition encounter dict. Returns render-ready data."""
    meta = record.get("metadata", {})
    ls = record.get("patient_context", {}).get("longitudinal_summary", {})

    states = build_states(record)          # <-- REAL parsing + engine
    cards = [_card(s) for s in states]

    surfaced   = sum(1 for c in cards if c["surfaced"])
    suppressed = sum(1 for c in cards if not c["surfaced"])
    verify     = sum(1 for c in cards if c["route_class"] == "verify")

    return {
        "title": meta.get("visit_title", "Encounter"),
        "date": meta.get("date", "")[:10],
        "n_encounters": ls.get("resource_counts", {}).get("Encounter", "?"),
        "med_count": len(ls.get("medication_labels", [])),
        "cards": cards,
        "stats": {"surfaced": surfaced, "suppressed": suppressed,
                  "verify": verify},
        "engine": "live",   # marker: this came from the real pipeline, not a fixture
    }


if __name__ == "__main__":
    import json, sys
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "data/synthetic-ambient-fhir-25.jsonl"
    idx = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    rec = json.loads(open(path).readlines()[idx])
    import pprint; pprint.pprint(analyze_encounter(rec))
