"""
safety_eval.py — the evaluation this project actually needs (per technical feedback).

Reports CONTROLLED CHECKS, never "accuracy". Three parts:
  1. Field-level scorer      — locate errors (action / evidence / resolution / disposition)
  2. False-suppression suite — the highest-cost error: closing a live issue as resolved
  3. Small adversarial set   — cases designed to be hard, not easy

Cost asymmetry (explicit): false suppression >> unnecessary surface. A dangerous
issue silently closed can harm; an extra question merely annoys. They are counted
separately and never averaged.
"""
from trajectory import TrajectoryState, EvidenceItem, Commitment, surface_question

# ---------- field-level scoring ----------
FIELDS = ("action", "evidence_relation", "resolution", "disposition")

def score_fields(got: TrajectoryState, expected: dict):
    rows = []
    checks = {
        "action": got.action,
        "evidence_relation": got.evidence_relation(),
        "resolution": got.resolution,
        "disposition": got.disposition(),
    }
    for f in FIELDS:
        exp = expected.get(f)
        if exp is None:
            continue
        rows.append((f, checks[f], exp, checks[f] == exp))
    return rows

# ---------- adversarial / hard cases (authored to be tricky) ----------
def C(target, level, cue=None): return Commitment(target, level, cue)
def E(rel, src, ts, a=""): return EvidenceItem(rel, a, src, ts)

ADVERSARIAL = [
    # 1. clinician-APPROVED reduction: looks like nonadherence, but is fine.
    #    MUST NOT be surfaced as a discrepancy (disposition != ask_patient).
    ("clinician_approved_reduction",
     TrajectoryState("t","adv1","QD","doctor approved once daily","self_reduced",
        [C("approved_change","neutral")],
        [E("support","pulmonology_note","2026-06-15"),
         E("contradict","medication_list","2026-04-01")],
        "documented","resolved"),
     {"evidence_relation":"source_conflict","disposition":"verify_current_regimen"}),

    # 2. ambiguous action: patient vague about whether they stopped.
    #    Should NOT be over-read as discontinued.
    ("ambiguous_action",
     TrajectoryState("t","adv2","unknown","not sure, sometimes I forget","self_reduced",
        [C("adherence","hedged","sometimes")],
        [E("contradict","MedicationRequest","2026-03-14")],
        "partially_addressed","unaddressed"),
     {"action":"self_reduced","disposition":"ask_patient"}),

    # 3. adverse-effect rationale (same drug, DIFFERENT relation than sufficiency).
    ("adverse_effect_rationale",
     TrajectoryState("t","adv3","reduced","it made my hands shake","self_reduced",
        [C("adverse_effect","emphatic","shake")],
        [E("contradict","MedicationRequest","2026-03-14")],
        "unaddressed","unaddressed"),
     {"action":"self_reduced","disposition":"ask_patient"}),

    # 4. resolved-then-REOPENED: was settled, patient reverted. Must resurface.
    ("resolved_then_reopened",
     TrajectoryState("t","adv4","none","I stopped again","discontinued",
        [C("discontinuation","emphatic","stopped again")],
        [E("contradict","MedicationRequest","2026-03-14")],
        "noted","reopened"),
     {"action":"discontinued","disposition":"ask_patient"}),

    # 5. no actionable issue: patient adherent, record agrees. Must stay quiet.
    ("no_issue",
     TrajectoryState("t","adv5","BID","taking it as prescribed","resumed",
        [C("adherence","neutral")],
        [E("support","medication_list","2026-06-01")],
        "resolved","resolved"),
     {"evidence_relation":"support","disposition":"none"}),
]

# ---------- false-suppression suite (highest-cost error) ----------
# Each case is a state that MUST surface (or route), i.e. must NOT be silently
# closed. A false suppression here is the dangerous failure.
def must_not_suppress(state: TrajectoryState) -> bool:
    q = surface_question(state)
    routed = state.disposition() in ("ask_patient", "verify_current_regimen")
    return (q is not None) or routed

FALSE_SUPPRESSION = [
    ("unresolved_not_closed", ADVERSARIAL[1][1]),   # ambiguous, unaddressed
    ("reopened_resurfaces",   ADVERSARIAL[3][1]),   # reopened discontinuation
    ("adverse_effect_asked",  ADVERSARIAL[2][1]),   # adverse-effect reduction
]

if __name__ == "__main__":
    print("="*64); print("SAFETY / CONTROLLED-CHECK EVALUATION"); print("="*64)

    print("\n[1] Field-level checks on adversarial cases:")
    field_pass = field_total = 0
    for name, state, expected in ADVERSARIAL:
        rows = score_fields(state, expected)
        oks = sum(1 for *_, ok in rows if ok)
        field_pass += oks; field_total += len(rows)
        marks = " ".join(f"{f}:{'OK' if ok else 'X'}" for f, *_ , ok in rows)
        print(f"  {name:32s} {marks}")

    print("\n[2] False-suppression suite (must NOT be silently closed):")
    fs_ok = 0
    for name, state in FALSE_SUPPRESSION:
        ok = must_not_suppress(state)
        fs_ok += ok
        print(f"  {name:32s} surfaced/routed={ok}  {'OK' if ok else 'DANGER: false suppression'}")

    print("\n" + "="*64)
    print(f"Field-level checks: {field_pass}/{field_total} fields correct")
    print(f"False-suppression:  {fs_ok}/{len(FALSE_SUPPRESSION)} high-risk cases correctly kept open")
    print("\nReported as CONTROLLED CHECKS over authored cases — NOT accuracy,")
    print("NOT risk recall, NOT generalization. High-risk false suppression target = 0.")
