"""
RES0216 end-to-end: extraction (v3) -> Stage 2/3/4 -> clarifying questions.

Two modes:
  python3 res0216_end2end.py --mock    # no API key; uses the real v3 output as
                                        # hardcoded Claims to verify the WIRING
  python3 res0216_end2end.py           # live: runs the actual 2-pass extraction
                                        # (needs ANTHROPIC_API_KEY)

The compare step here is demo-grade: it routes a claim by its MEANING
(adherence self-assessment / sufficiency self-assessment / explicit frequency /
prescription restatement) rather than string-matching a fixed phrase. Generalizing
this is future work; for RES0216 it produces the intended three-part story.
"""

import sys
from dataclasses import dataclass, field
from typing import Optional


# ---- shared shape (kept identical to the extractor) -------------------------
@dataclass
class Cue:
    type: str
    token: str

@dataclass
class Claim:
    utterance_id: str
    text: str
    speech_act: str
    claim: str
    target_resource: Optional[str]
    cues: list = field(default_factory=list)


# ---- Stage 0: record fixture ------------------------------------------------
import os
from fhir_record import build_record

# Stage 0 now comes from a REAL Synthea FHIR bundle, not a hand-built dict.
# Override the path with BUNDLE_PATH=... if needed.
BUNDLE_PATH = os.environ.get(
    "BUNDLE_PATH",
    "output/fhir/Pearl430_Ziemann98_e7e2e3bd-7bb1-af8e-8c53-94393768ce6e.json",
)
# The Synthea bundle isn't vendored in this repo (see README — referenced, not
# redistributed). Load it if present; otherwise leave RECORD empty so importing
# this module never crashes. The demo path (run_trajectory.py) uses V1_META, not
# this bundle, so absence here is harmless.
try:
    RECORD, RECORD_META = build_record(BUNDLE_PATH)
except FileNotFoundError:
    RECORD, RECORD_META = {}, {}
# NOTE: this record is an asthma patient (Pearl430). The RES0216 utterance also
# mentions hypertension/Ramipril; those have no counterpart here (utterance and
# record come from different people, by design — Synthea supplies no speech), so
# bp/htn claims resolve to "silent". The controller/rescue overlap is the demo.

SLUG_TO_ID = {
    "controller-inhaler": "mr-controller",
    "rescue-inhaler":     "mr-rescue",
    "bp-medication":      "rx-bp",             # not in this record -> silent
    "hypertension-diagnosis": "dx-htn",        # not in this record -> silent
}


# ---- Stage 2: expressed certainty as a GRADE, not an arbitrary score --------
# Linguistic basis (so grades aren't hand-tuned numbers):
#   strengthener = booster   |   weakener = hedge
#   evidential   = authority / self_justification (can strengthen, not factive)
# Gradient continuum (Rubin 2010): absolute > high > moderate > low > uncertain.
# Anchors: Rubin (2010) epistemic gradient; "Navigating the Grey Area"
# (strengthener/weakener); BioScope / Velupillai (clinical certainty annotation).
FACTIVE = ("always", "never", "definitely", "for sure", "no problem",
           "any problem", "haven't had any", "100", "certain", "no doubt", "know")
GRADE_RANK = {"absolute": 4, "high": 3, "moderate": 2, "low": 1, "uncertain": 0, "unmarked": 0}

def _has(cues, ctype):
    return any(c.type == ctype for c in cues)

def _is_factive(cues):
    return any(c.type == "booster" and any(f in c.token.lower() for f in FACTIVE)
               for c in cues)

def certainty_grade(claim: Claim):
    if claim.speech_act != "assertion":
        return None, "not an assertion"
    strengthener = _has(claim.cues, "booster")
    weakener     = _has(claim.cues, "hedge")
    evidential   = _has(claim.cues, "authority") or _has(claim.cues, "self_justification")
    if strengthener and weakener:
        return "moderate", "strengthener and weakener both present (conflicting)"
    if strengthener and not weakener:
        return ("absolute", "factive strengthener, no weakener") if _is_factive(claim.cues) \
               else ("high", "strengthener present, no weakener")
    if not strengthener and evidential and not weakener:
        return "moderate", "evidential backing only, no categorical strengthener"
    if weakener and not strengthener:
        return ("low", "weakener with some evidential backing") if evidential \
               else ("uncertain", "weakener only")
    return "unmarked", "no epistemic marking"

# NOTE: certainty is NOT a gate. Candidacy is decided by evidence relation in run().
# Certainty only *modifies* rank (via GRADE_RANK). This helper is kept only to name
# the "high certainty" tiers for readability; it must never gate candidate creation.
def is_high_certainty(grade):
    return grade in ("absolute", "high")


# ---- Stage 3: record comparison --------------------------------------------
def detect_frequency(text: str):
    t = text.lower()
    if "once daily" in t or "morning only" in t:
        return 1
    if "twice daily" in t or "morning and night" in t:
        return 2
    return None

def patient_reported_controller_freq(claims):
    """Find the patient's plain frequency report for the controller (not an
    adherence or sufficiency self-assessment)."""
    for c in claims:
        if SLUG_TO_ID.get(c.target_resource) != "mr-controller":
            continue
        t = c.claim.lower()
        if "adherent" in t or "prescribed" in t or is_sufficiency_claim(t):
            continue
        f = detect_frequency(t)
        if f:
            return f
    return None

def is_sufficiency_claim(t: str) -> bool:
    """A self-assessment that the current (reduced) regimen is working / fine,
    as opposed to a fresh frequency report. Robust to phrasing like
    'no respiratory problems', 'no issues', 'haven't had any problems'."""
    t = t.lower()
    if any(k in t for k in ("sufficient", "enough", "no issue", "no trouble",
                            "working fine", "works fine", "well controlled")):
        return True
    # negated "problem(s)": "no ... problems", "haven't had any problems", etc.
    if "problem" in t and any(neg in t for neg in
                              ("no ", "without", "haven't", "n't", "not ", "never")):
        return True
    return False


def compare_to_record(claim: Claim, actual_controller_freq):
    rid = SLUG_TO_ID.get(claim.target_resource)
    if rid is None or rid not in RECORD:
        return "silent", "not represented in this record"
    res = RECORD[rid]
    t = claim.claim.lower()

    if rid == "mr-controller":
        presc = res["prescribed_freq_per_day"]
        actual = res.get("actual_freq_per_day")   # derived from refill-interval history
        # 1) adherence self-assessment -> checked against the REFILL RECORD
        if "adherent" in t or "as prescribed" in t or "as directed" in t:
            if actual is not None and actual < presc:
                return "contradict", (f"claims full adherence, but refill history implies "
                                      f"~{actual}/day vs prescribed {presc}/day")
            return "silent", "adherence not verifiable from record"
        # 2) sufficiency self-assessment (before frequency)
        if is_sufficiency_claim(t):
            return "silent", "record does not state the reduced regimen was clinician-approved"
        # 3) prescription restatement
        f = detect_frequency(t)
        if f and f == presc:
            return "support", "matches the prescribed regimen"
        # 4) explicit patient frequency that diverges from prescription
        if f and f != presc:
            return "contradict", f"patient reports {f}/day; prescribed {presc}/day"
        return "silent", "no matching record assertion"

    if rid == "mr-rescue":
        if any(k in t for k in ("not refill", "not needed", "haven't needed", "not been needed")):
            return "support", "no recent dispense on record; consistent with non-use"
        return "support", "rescue medication is on record"

    if rid == "rx-bp":
        return "support", "antihypertensive is on record"
    if rid == "dx-htn":
        return "support", "diagnosis is on record"
    return "silent", "unhandled resource"


# ---- Stage 4: Axis B gate + clarifying question -----------------------------
def is_consequential(claim: Claim, evidence: str):
    """First gate (before evidence/certainty): is this worth a clinician's attention
    at all? A claim qualifies only if the patient has TAKEN AN ACTION or made a
    treatment SELF-ASSESSMENT — not for bare facts or mere record incompleteness.

    This is the 'clinical relevance / action gate' the pipeline needs. Without it,
    removing the certainty gate would make every `silent` line a candidate
    (an alert-fatigue machine). Action-taken passes even with no certainty cue.
    """
    t = claim.claim.lower()
    action_markers = ("reduc", "stop", "skip", "discontinu", "cut", "halv",
                      "only in the morning", "once daily", "once a day",
                      "self-", "on my own", "without asking")
    assessment_markers = ("sufficient", "enough", "no problem", "no issue",
                          "fine without", "don't need", "doesn't need", "adherent")
    has_action = any(m in t for m in action_markers)
    has_assessment = any(m in t for m in assessment_markers)
    # a plain record contradiction on a treatment claim is also consequential
    treatment_contradiction = (evidence == "contradict")
    return has_action or has_assessment or treatment_contradiction


def clarifying_question(claim: Claim, evidence: str):
    t = claim.claim.lower()
    if "adherent" in t and evidence == "contradict":
        return ("Patient reports full adherence to the controller, but the prescription "
                "is twice daily and reported use is once daily. Confirm current dosing "
                "and whether the reduction was intentional.")
    if is_sufficiency_claim(t) and evidence == "silent":
        return ("Patient is confident the once-daily regimen is sufficient. Was this "
                "step-down reviewed with a clinician, or self-directed?")
    # explicit regimen-frequency divergence (patient QD vs prescribed BID)
    if evidence == "contradict" and ("once daily" in t or "morning only" in t):
        return ("Patient reports once-daily use but the controller is prescribed twice "
                "daily. Confirm the current regimen and whether the change was intended.")
    # no specific, useful question -> do not surface (avoid alert fatigue)
    return None


def run(claims):
    c = RECORD_META.get("controller", {})
    if c:
        print(f"RECORD source: {c.get('med')}")
        print(f"  {c.get('n_refills')} refills, median gap ~{c.get('median_refill_gap_days')}d "
              f"-> derived actual ~{c.get('derived_actual_freq_per_day')}/day "
              f"(prescribed 2/day)\n")
    actual_freq = patient_reported_controller_freq(claims)
    flags = []
    for c in claims:
        grade, why_grade = certainty_grade(c)
        evidence, why = compare_to_record(c, actual_freq)

        # GATE order (per feedback pipeline):
        #  1) clinical relevance / action gate  (is it worth attention at all?)
        #  2) evidence relation                 (does the record disagree / stay silent?)
        #  3) a specific, useful question exists (else don't surface -> no fatigue)
        #  certainty is applied later as a rank MODIFIER, never as a gate.
        q = clarifying_question(c, evidence) if evidence in ("contradict", "silent") else None
        candidate = (c.speech_act == "assertion"
                     and is_consequential(c, evidence)
                     and evidence in ("contradict", "silent")
                     and q is not None)

        cue_str = ", ".join(f"{x.type}:{x.token!r}" for x in c.cues) or "(none)"
        print(f"[{c.utterance_id}] {c.claim}")
        print(f"    target={c.target_resource}  Axis A={evidence}  ({why})")
        if grade is None:
            print(f"    certainty=N/A ({c.speech_act})")
        else:
            print(f"    certainty={grade}  ({why_grade})  [{cue_str}]   "
                  f"candidate={'YES' if candidate else '-'}")
        if candidate:
            print(f"    --> ASK: {q}")
            flags.append((c, evidence, grade, q))
        print()

    # ---- priority ranking: evidence severity first, certainty as a MODIFIER ---
    print("=" * 70)
    print("PRIORITIZED CLARIFYING QUESTIONS:\n")
    sev = {"contradict": 2, "silent": 1}
    flags.sort(key=lambda f: (sev.get(f[1], 0), GRADE_RANK.get(f[2], 0)), reverse=True)
    for i, (c, evidence, grade, q) in enumerate(flags, 1):
        print(f"{i}. [{evidence}; certainty={grade} (modifier)] {q}\n")


# ---- the real v3 output, as Claims, for --mock wiring test ------------------
def mock_claims():
    C = lambda *a, cues=[]: Claim(*a, cues=cues)
    return [
        C("P-17", "", "assertion", "uses a daily controller inhaler", "controller-inhaler"),
        C("P-17", "", "assertion", "has not refilled the rescue inhaler because it has not been needed in a long time", "rescue-inhaler"),
        C("P-18", "", "assertion", "has not needed the rescue inhaler for approximately two years", "rescue-inhaler"),
        C("P-18", "", "assertion", "continues to take the daily controller inhaler", "controller-inhaler"),
        C("P-19", "", "assertion", "is fully adherent to the controller inhaler regimen", "controller-inhaler",
          cues=[Cue("booster", "always")]),
        C("P-19", "", "assertion", "the controller inhaler is prescribed twice daily, morning and night", "controller-inhaler",
          cues=[Cue("authority", "I'm supposed to")]),
        C("P-19", "", "assertion", "previously skipped the nightly dose of the controller inhaler at times due to not feeling it was needed", "controller-inhaler",
          cues=[Cue("hedge", "sometimes")]),
        C("P-19", "", "assertion", "currently takes the controller inhaler once daily in the morning only", "controller-inhaler"),
        C("P-20", "", "assertion", "has not needed the rescue inhaler in a few years", "rescue-inhaler"),
        C("P-20", "", "assertion", "has experienced no problems while taking the controller inhaler once daily in the morning only", "controller-inhaler",
          cues=[Cue("booster", "haven't had any problems")]),
        C("P-24", "", "assertion", "has a diagnosis of hypertension", "hypertension-diagnosis"),
        C("P-24", "", "assertion", "has infrequent contact with their doctor", None),
        C("P-24", "", "assertion", "manages hypertension with medication only, without frequent medical follow-up", "bp-medication"),
        C("P-25/26", "", "assertion", "takes salbutamol", "rescue-inhaler"),
        C("P-25/26", "", "assertion", "takes Ramipril", "bp-medication"),
    ]


if __name__ == "__main__":
    print("=== RES0216 end-to-end ===\n")
    if "--mock" in sys.argv:
        print("(mock mode: using saved v3 extraction, no API call)\n")
        claims = mock_claims()
    else:
        from res0216_extract_v3 import pass1_claims, pass2_cues, _client
        client = _client()
        claims = pass1_claims(client)
        for c in claims:
            c.cues = pass2_cues(client, c)
    run(claims)
