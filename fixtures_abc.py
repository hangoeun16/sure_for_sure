"""
fixtures_abc.py — expected trajectory states (authored BEFORE dialogue) + answer key.
Updated for feedback fixes: per-claim commitments, clinical_course (co-occurrence,
not causal), tier-based priority, disposition instead of patient_is_wrong.
"""
# NOTE: Visit 1 (V1) reflects transcript RES0216, a real de-identified clinical
# encounter from chicago-aiscience/Clinical_KG_OS_LLM (BSD-3-Clause). Short excerpts
# are used here under that license with attribution; the full transcript is not
# vendored in this repo. See README.md and LICENSE.


from trajectory import (
    TrajectoryState, EvidenceItem, Commitment,
    priority, priority_tier, priority_drivers, surface_question, trajectory_change,
)

TOPIC = "asthma-controller-regimen"
RX_BID = EvidenceItem("contradict", "prescribed BID", "MedicationRequest", "2026-03-14")

# ---- Visit 1 (RES0216, real) — commitment PER CLAIM ----
V1 = TrajectoryState(
    topic_id=TOPIC, encounter_id="V1",
    regimen_reported="QD",
    assessment="reduced regimen has been sufficient",
    action="self_reduced",
    commitments=[
        Commitment("daily_use", "emphatic", "always"),
        Commitment("QD_sufficiency", "emphatic", "haven't had any problems"),
        Commitment("full_prescription_adherence", "not_asserted"),
    ],
    evidence=[RX_BID],
    clinician_response="elicited_rationale",
    resolution="partially_addressed",
)

# ---- Branch A: escalation (full V2, V3) ----
A_V2 = TrajectoryState(
    topic_id=TOPIC, encounter_id="A-V2",
    regimen_reported="QD",
    assessment="still sufficient; attributes worsening to weather",
    action="self_reduced",
    commitments=[Commitment("QD_sufficiency", "emphatic", "I was fine on one dose")],
    evidence=[RX_BID,
              EvidenceItem("contradict", "nighttime symptoms + rising rescue use",
                           "Observation", "2026-05-01")],
    clinician_response="advised_but_not_accepted",
    resolution="unaddressed",
    clinical_course="night symptoms up, rescue use up",
)

A_V3 = TrajectoryState(
    topic_id=TOPIC, encounter_id="A-V3",
    regimen_reported="none",
    assessment="it wasn't helping anyway",
    action="discontinued",
    commitments=[Commitment("discontinuation_justified", "emphatic", "wasn't doing anything")],
    # symptom worsening lives in clinical_course (co-occurrence), NOT as record
    # evidence. The record evidence here is the standing BID prescription the
    # patient has now fully stopped.
    evidence=[RX_BID],
    clinician_response="noted",
    resolution="unaddressed",
    clinical_course="rescue use frequent, nocturnal symptoms, activity limited",
)

# ---- Branch B: resolution (thin) ----
B_V2 = TrajectoryState(
    topic_id=TOPIC, encounter_id="B-V2",
    regimen_reported="BID",
    assessment="will resume BID as intended",
    action="resumed",
    commitments=[Commitment("plan_agreement", "neutral")],
    evidence=[EvidenceItem("support", "clinician-confirmed BID restart, documented",
                           "plan_note", "2026-05-02")],
    clinician_response="confirmed_plan_patient_acknowledged",
    resolution="resolved",
)

B_V3 = TrajectoryState(
    topic_id=TOPIC, encounter_id="B-V3",
    regimen_reported="BID",
    assessment="no new concern",
    action="resumed",
    commitments=[Commitment("routine", "neutral")],
    evidence=[EvidenceItem("support", "BID use consistent", "medication_list", "2026-06-01")],
    clinician_response="none_needed",
    resolution="resolved",
)

# ---- Branch C: record lag (thin, timestamped dual sources) ----
C_V2 = TrajectoryState(
    topic_id=TOPIC, encounter_id="C-V2",
    regimen_reported="QD",
    assessment="doctor approved once-daily",
    action="self_reduced",
    commitments=[Commitment("approved_change", "neutral")],
    evidence=[
        EvidenceItem("support",    "clinician-approved step-down to QD",
                     "pulmonology_note", "2026-06-15"),
        EvidenceItem("contradict", "controller BID",
                     "medication_list", "2026-04-01"),
    ],
    clinician_response="reconciled_record_in_visit",
    resolution="resolved",
)


if __name__ == "__main__":
    for s in (V1, A_V2, A_V3):
        print(f"{s.encounter_id}: tier={priority_tier(s)} score={priority(s)} "
              f"disp={s.disposition()} drivers={priority_drivers(s)}")
    print(f"B-V2: tier={priority_tier(B_V2)} resolution={B_V2.resolution}")
    print(f"B-V3 question: {surface_question(B_V3)}")
    print(f"C-V2: rel={C_V2.evidence_relation()} disp={C_V2.disposition()} "
          f"lag={C_V2.possible_record_lag()}")
    print(f"C-V2 carry_forward: {C_V2.carry_forward()}")
    print()

    # ANSWER KEY
    # A: escalation ordering holds (internal score) AND tiers rise
    assert priority(A_V2) > priority(V1)
    assert priority(A_V3) > priority(A_V2)
    assert priority_tier(A_V3) == "Urgent clarification"

    # B: resolved -> suppressed, no question
    assert B_V2.resolution == "resolved"
    assert surface_question(B_V3) is None
    assert priority_tier(B_V2) == "Suppressed"

    # C: source_conflict, disposition is record reconciliation (NOT blame patient)
    assert C_V2.evidence_relation() == "source_conflict"
    assert C_V2.disposition() == "verify_current_regimen"
    assert C_V2.carry_forward()["work_type"] == "record_reconciliation"

    # each branch produces a DIFFERENT kind of follow-up work
    assert A_V3.carry_forward()["work_type"] == "clinical_question"
    assert B_V2.carry_forward()["work_type"] == "none"
    assert C_V2.carry_forward()["work_type"] == "record_reconciliation"

    # commitment is per-claim: V1 asserts sufficiency but NOT full adherence
    scopes = {c.target: c.level for c in V1.commitments}
    assert scopes["full_prescription_adherence"] == "not_asserted"
    assert scopes["QD_sufficiency"] == "emphatic"

    print("ALL ANSWER-KEY ASSERTS PASS")
