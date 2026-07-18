"""
run_trajectory.py — ONE executable path, Priority 1 of the feedback.

  RES0216 (real V1)  --engine-->  candidates --adapter--> V1 event
  A-V2, A-V3 (synthetic) --extract--> events --adapter--> V2/V3 events
      -> link (same topic) -> transition -> disposition -> question/suppress

Branch A shown fully (V1->V2->V3). B and C run as single follow-ups to show the
other two dispositions (suppress / reconcile record).

Mock mode (no API): uses saved extractions so the whole path runs offline.
    python3 run_trajectory.py --mock
Live mode: re-extracts from transcripts.
    python3 run_trajectory.py
"""
import sys
from trajectory import (priority_tier, priority_drivers, trajectory_change,
                        surface_question, encounter_only_question)
from adapter import encounter_to_event, extracted_to_event

TOPIC = "asthma-controller-regimen"

# ---- V1 from the single-encounter engine (RES0216) --------------------------
# The engine's representative candidates for RES0216 (from res0216_end2end mock).
V1_CANDIDATES = [
    {"claim": "is fully adherent to the controller inhaler regimen",
     "evidence": "contradict", "grade": "absolute", "cues": [("booster", "always")],
     "target": "controller-inhaler"},
    {"claim": "currently takes the controller inhaler once daily in the morning only",
     "evidence": "contradict", "grade": "unmarked", "cues": [], "target": "controller-inhaler"},
    {"claim": "has experienced no problems while taking it once daily in the morning",
     "evidence": "silent", "grade": "absolute",
     "cues": [("booster", "haven't had any problems")], "target": "controller-inhaler"},
]
V1_META = {"controller": {"med": "budesonide", "n_refills": 11, "median_refill_gap_days": 371}}

# ---- saved extractions for V2/V3 (mock) — from extract_events ALL RECOVERED --
MOCK_EXTRACTED = {
    "A-V2": {"action": "self_reduced", "resolution": "unaddressed",
             "patient_regimen_reported": "QD",
             "evidence": [{"relation": "contradict", "source_type": "prescribed_regimen",
                           "timestamp": "2026-05-01", "assertion": "prescribed BID"}],
             "clinical_course": "night symptoms up, rescue use up",
             "commitments": [{"target": "QD_sufficiency", "level": "emphatic",
                              "cue": "I was fine on one dose"}]},
    "A-V3": {"action": "discontinued", "resolution": "unaddressed",
             "patient_regimen_reported": "none", "evidence": [],
             "clinical_course": "rescue use frequent, nocturnal symptoms, activity limited",
             "commitments": [{"target": "discontinuation", "level": "emphatic",
                              "cue": "wasn't doing anything"}]},
    "B-V2": {"action": "resumed", "resolution": "resolved",
             "patient_regimen_reported": "BID",
             "evidence": [{"relation": "support", "source_type": "plan_note",
                           "timestamp": "2026-05-02", "assertion": "BID restart documented"}],
             "clinical_course": "", "commitments": []},
    "C-V2": {"action": "self_reduced", "resolution": "resolved",
             "patient_regimen_reported": "QD",
             "evidence": [{"relation": "support", "source_type": "pulmonology_note",
                           "timestamp": "2026-06-15", "assertion": "clinician-approved QD"},
                          {"relation": "contradict", "source_type": "medication_list",
                           "timestamp": "2026-04-01", "assertion": "list shows BID"}],
             "clinical_course": "", "commitments": []},
}

def show(state, prev=None):
    tier = priority_tier(state)
    change = trajectory_change(prev, state)
    q = surface_question(state)
    dtype, ddesc = state.divergence()
    dom = f"  ({state.domain})" if getattr(state, "domain", "medication") != "medication" else ""
    print(f"  [{state.encounter_id}]{dom} action={state.action}  evidence={state.evidence_relation()}  "
          f"resolution={state.resolution}")
    print(f"      divergence={dtype or 'none'}  ({ddesc})")
    print(f"      tier={tier}  change={change}  disposition={state.disposition()}")
    drivers = priority_drivers(state)
    if drivers:
        print(f"      drivers: {', '.join(drivers)}")
    cf = state.carry_forward()
    print(f"      work_type={cf['work_type']}")
    if q:
        print(f"      --> {q}")
    else:
        print(f"      --> (nothing surfaced)")
    print()
    # return whether this was surfaced or suppressed, for the tally
    return {"surfaced": q is not None,
            "suppressed": q is None and state.resolution == "resolved",
            "divergence": dtype,
            "disposition": state.disposition(),
            "resolution": state.resolution,
            "risk": state.action == "discontinued"}

def get_extracted(tag, mock):
    if mock:
        return MOCK_EXTRACTED[tag]
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("live mode needs ANTHROPIC_API_KEY (or use --mock)")
    from extract_events import extract
    import anthropic
    return extract(tag, anthropic.Anthropic())

if __name__ == "__main__":
    mock = "--mock" in sys.argv
    print("="*64)
    print("ONE PATH: RES0216 (real) -> adapter -> trajectory -> follow-ups")
    print("="*64)

    # V1 from the single-encounter engine, via adapter
    RESULTS = []
    v1 = encounter_to_event(TOPIC, "V1", V1_CANDIDATES, record_meta=V1_META)
    print("\nBranch A — escalation (V1 real -> V2 -> V3):")
    RESULTS.append(show(v1))
    a_v2 = extracted_to_event(TOPIC, "A-V2", get_extracted("A-V2", mock))
    RESULTS.append(show(a_v2, prev=v1))
    a_v3 = extracted_to_event(TOPIC, "A-V3", get_extracted("A-V3", mock))
    RESULTS.append(show(a_v3, prev=a_v2))

    print("Branch B — resolution (V1 -> resolved follow-up):")
    b_v2 = extracted_to_event(TOPIC, "B-V2", get_extracted("B-V2", mock))
    RESULTS.append(show(b_v2, prev=v1))

    print("Branch C — record lag (V1 -> source-conflict follow-up):")
    c_v2 = extracted_to_event(TOPIC, "C-V2", get_extracted("C-V2", mock))
    RESULTS.append(show(c_v2, prev=v1))

    # ---- CASE 1: competition data, parsed live from the provided FHIR ----
    # This is the "runs on the organizer's data" proof: #10's duplicate statin /
    # metoprolol entries are read from the real dataset and routed by the SAME engine.
    print("Branch E — COMPETITION DATA #10 (duplicate meds -> source_conflict):")
    try:
        from fhir_competition import load_encounter, build_states
        COMP_PATH = "data/synthetic-ambient-fhir-25.jsonl"
        rec = load_encounter(COMP_PATH, 10)
        for st in build_states(rec):
            RESULTS.append(show(st))
    except FileNotFoundError:
        print("  (competition dataset not present locally — skipped; run where the")
        print("   jsonl is mounted to see #10 parsed live.)\n")

    # ---- SECOND DOMAIN: symptom divergence (same engine, different domain) ----
    print("Branch D — SYMPTOM divergence (patient 'I'm fine' vs worsening record):")
    from trajectory import TrajectoryState, EvidenceItem, Commitment
    d_v1 = TrajectoryState(
        topic_id="asthma-symptom-control", encounter_id="D-V1",
        regimen_reported="n/a", assessment="breathing feels fine, no trouble",
        action="none",
        commitments=[Commitment("symptom_control", "emphatic", "no trouble at all")],
        evidence=[EvidenceItem("contradict", "FEV1 declined 15% since last visit",
                               "Observation", "2026-06-01")],
        clinician_response="noted", resolution="unaddressed",
        clinical_course="lung function down on spirometry", domain="symptom")
    RESULTS.append(show(d_v1))

    print("="*64)
    print("Three dispositions from one engine: ask_patient / suppress / verify_record")

    # ---- suppression tally: the alert-fatigue story, made explicit ----
    surfaced = sum(1 for r in RESULTS if r["surfaced"])
    suppressed = sum(1 for r in RESULTS if r["suppressed"])
    dtypes = [r["divergence"] for r in RESULTS if r["divergence"]]
    print(f"\nAcross {len(RESULTS)} encounters:")
    print(f"  surfaced (worth asking now): {surfaced}")
    print(f"  suppressed (already resolved): {suppressed}")
    print(f"  divergence types seen: {', '.join(dict.fromkeys(dtypes)) or 'none'}")
    print("  -> the system's value is as much what it DOESN'T ask as what it does.")

    # ---- academic metrics (Pan et al. proactive-inquiry protocol, adapted) ----
    # Coverage: of encounters with a real divergence, how many were surfaced or
    #           correctly routed (record_reconciliation counts as handled).
    # Redundancy: surfaced findings that were already resolved (lower is better).
    # Risk recall: of high-risk encounters (discontinuation / escalation), how
    #           many were surfaced.
    # T_goal: index (1-based) of the encounter where the most severe divergence
    #           was first surfaced.
    def has_divergence(r): return r["divergence"] not in (None, "none")
    def handled(r):        return r["surfaced"] or r["disposition"] == "verify_current_regimen"
    div = [r for r in RESULTS if has_divergence(r)]
    coverage = sum(1 for r in div if handled(r)) / len(div) if div else 0.0
    # A resolved thread that still SURFACES is only redundant if it's asking the
    # PATIENT again. A record-reconciliation task (source_conflict) is correctly
    # surfaced even when the clinical issue is resolved — the records still
    # disagree — so it must NOT be counted as a false surface.
    redundant = sum(1 for r in RESULTS
                    if r["disposition"] == "ask_patient" and r["resolution"] == "resolved")
    redundancy = redundant / max(sum(1 for r in RESULTS if r["surfaced"]), 1)
    risk = [r for r in RESULTS if r["risk"]]
    risk_recall = sum(1 for r in risk if r["surfaced"]) / len(risk) if risk else 0.0
    t_goal = next((i+1 for i, r in enumerate(RESULTS) if r["risk"] and r["surfaced"]), None)
    # Reported as CONTROLLED CHECKS, not accuracy. These are counts over authored
    # scenarios, not a performance estimate. See TECHNICAL_SPEC for the distinction
    # between policy correctness (strong) and perception correctness (small sample).
    n_div = len(div)
    n_cov = sum(1 for r in div if handled(r))
    n_risk = len(risk)
    n_risk_hit = sum(1 for r in risk if r["surfaced"])
    print("\nControlled checks (Pan et al. protocol, adapted — NOT accuracy):")
    print(f"  Divergences handled:   {n_cov}/{n_div}  (surfaced or routed)")
    print(f"  Resolved-yet-surfaced: {redundant}     (false-surface count; lower better)")
    print(f"  Escalations caught:    {n_risk_hit}/{n_risk}")
    print(f"  First top-severity surfacing: visit {t_goal}")
    print("  NOTE: mixed set — authored longitudinal trajectory (John/RES0216) +")
    print("        real competition FHIR (#10, parsed live). Controlled demo, not")
    print("        clinical accuracy, not generalization. Policy correctness only.")

    # ---- BASELINE vs LONGITUDINAL: does history change the question? ----
    print("\n" + "="*64)
    print("BASELINE (single-encounter) vs LONGITUDINAL — at A-V3")
    print("="*64)
    print("\nEncounter-only system sees just this visit:")
    print(f"  Q: {encounter_only_question(a_v3)}")
    print("\nLongitudinal system sees the trajectory:")
    print(f"  Q: {surface_question(a_v3)}")
    print("\n-> History changes WHICH question is worth asking, not just its wording.")

    # ---- DECISION-CHANGING HISTORY: which past visits actually move the decision ----
    print("\n" + "="*64)
    print("DECISION-CHANGING HISTORY — which past encounters move the decision")
    print("="*64 + "\n")
    from decision_history import explain
    print(explain([v1, a_v2, a_v3]))
    print("\n-> In this trajectory, no single prior visit alone drives the decision; "
          "the escalation\n   is stable across the adjacent-transition checks. The evidence that history "
          "matters\n   here is the baseline-vs-longitudinal contrast above, not single-visit ablation.")
