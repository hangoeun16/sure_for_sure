"""
trajectory.py — longitudinal state schema + domain-NEUTRAL engine.

Refactor (post-hackathon architecture):
 - evidence_relation now lives in evidence.py (one definition, imported here and
   by the scorer, so the two can no longer drift).
 - per-domain behavior (risk/question/drivers/routing) lives in policy.py. This
   file no longer contains `if domain == "symptom"` branches; it looks up
   policy_for(state). Adding a domain = one entry in policy.py, zero edits here.

Design invariants (unchanged):
 - priority is an ORDINAL TIER + named drivers, not a fake clinical-risk number.
 - the system never adjudicates the patient; `disposition` says what follow-up
   work the finding creates.
 - causal_relation stays "unresolved": temporal co-occurrence, never causation.
 - commitment is PER-CLAIM.
 - source_conflict outranks clinical resolution everywhere.
"""
from dataclasses import dataclass
from typing import Optional

from evidence import EvidenceItem, evidence_relation


def _as_rel(e):
    """Read the relation off an evidence entry, whether it's an EvidenceItem or a dict."""
    return e.relation if isinstance(e, EvidenceItem) else e.get("relation", "")
from policy import policy_for, RESOLUTION_OPEN, COMMIT_BONUS, ACTION_RISK

COMMITMENT   = ("hedged", "neutral", "emphatic", "unclear", "not_asserted")
ACTION       = ("none", "planned", "self_reduced", "discontinued", "resumed")
EVIDENCE_REL = ("support", "contradict", "silent", "source_conflict", "not_assessable")
RESOLUTION   = ("unaddressed", "partially_addressed", "resolved_pending_confirmation",
                "resolved", "reopened")
TRAJECTORY   = ("stable", "escalating", "deescalating", "resolved", "evidence_updated")
DISPOSITION  = ("none", "ask_patient", "verify_current_regimen", "monitor")
WORK_TYPE    = ("none", "clinical_question", "record_reconciliation")


@dataclass
class Commitment:
    target: str
    level: str
    cue: Optional[str] = None


@dataclass
class TrajectoryState:
    topic_id: str
    encounter_id: str
    regimen_reported: str
    assessment: str
    action: str
    commitments: list
    evidence: list
    clinician_response: str
    resolution: str
    clinical_course: str = ""          # co-occurrence description; NOT causal
    causal_relation: str = "unresolved"
    domain: str = "medication"         # medication | symptom | ... (see policy.py)

    # ---- evidence & divergence (domain-neutral) ----
    def evidence_relation(self):
        return evidence_relation(self.evidence)

    def possible_record_lag(self):
        return self.evidence_relation() == "source_conflict"

    def max_commitment(self):
        levels = [c.level for c in self.commitments]
        for lvl in ("emphatic", "neutral", "hedged", "unclear", "not_asserted"):
            if lvl in levels:
                return lvl
        return "not_asserted"

    def divergence(self):
        """THE novel signal: cross expressed certainty (Axis B) with evidence
        (Axis A) to name WHAT KIND of gap this is. Domain-neutral — a symptom
        'I'm fine' vs a worsening finding is the same contradicted_belief shape
        as a medication one. Returns (type, description) or (None, ...).
        """
        rel = self.evidence_relation()
        strong = self.max_commitment() == "emphatic"

        if rel == "source_conflict":
            # source_conflict has two causes; name them correctly.
            # (a) coexisting unadjudicable duplicates (not_assessable entries) —
            #     same-class entries on one list, no date basis. NOT a date lag.
            # (b) a newer source supporting + an older contradicting = record_lag.
            if any(_as_rel(e) == "not_assessable" for e in self.evidence):
                return ("duplicate_record",
                        "the record carries conflicting entries for the same "
                        "medication thread; which is current can't be read from the record")
            return ("record_lag",
                    "records disagree by date; patient account is not the problem")
        if rel == "support":
            return (None, "patient statement is supported by the record")
        if self.action in ("self_reduced", "discontinued") and not strong \
           and policy_for(self).allows_silent_drift:
            return ("silent_drift",
                    "treatment changed with little expressed rationale")
        if rel == "contradict" and strong:
            return ("contradicted_belief",
                    "confident claim that the record directly contradicts")
        if rel in ("silent", "not_assessable") and strong:
            return ("unverified_confidence",
                    "confident claim the record can neither confirm nor deny")
        if rel == "contradict":
            return ("contradicted_belief", "claim the record contradicts")
        return (None, "no material divergence")

    # ---- routing (neutral core + policy hint) ----
    def disposition(self):
        # record conflict is its own workstream, surviving clinical resolution.
        if self.evidence_relation() == "source_conflict":
            return "verify_current_regimen"
        if self.resolution in ("resolved", "resolved_pending_confirmation"):
            return "none"
        if policy_for(self).wants_ask(self):
            return "ask_patient"
        return "monitor"

    def carry_forward(self):
        rel = self.evidence_relation()
        # record conflict outranks clinical resolution.
        if rel == "source_conflict":
            return {"carry_forward": True, "work_type": "record_reconciliation",
                    "reasons": ["newer note and active medication list disagree by date"]}
        if self.resolution == "resolved":
            return {"carry_forward": False, "work_type": "none",
                    "reasons": ["current regimen clarified", "plan documented",
                                "patient acknowledged plan"]}
        reasons = []
        if self.action in ("self_reduced", "discontinued"):
            reasons.append("self-directed medication change")
        if rel == "contradict":
            reasons.append("documented regimen mismatch")
        if self.resolution in ("unaddressed", "partially_addressed", "reopened"):
            reasons.append("no explicit plan resolving the discrepancy")
        return {"carry_forward": True, "work_type": "clinical_question", "reasons": reasons}


# ---- priority (neutral shell; per-domain risk from policy) ----
def _priority_score(state: TrajectoryState) -> int:
    # source_conflict outranks resolution: a live record conflict still carries a
    # reconciliation priority even after the clinical issue is resolved.
    if state.evidence_relation() == "source_conflict":
        return 1
    if state.resolution in ("resolved", "resolved_pending_confirmation"):
        return 0
    score  = policy_for(state).risk(state)
    score += RESOLUTION_OPEN.get(state.resolution, 0) * 2
    score += COMMIT_BONUS.get(state.max_commitment(), 0)
    return score

def priority_tier(state: TrajectoryState) -> str:
    if state.evidence_relation() == "source_conflict":
        return "Record review"
    if state.resolution in ("resolved", "resolved_pending_confirmation"):
        return "Suppressed"
    s = _priority_score(state)
    if s >= 12:  return "Urgent clarification"
    if s >= 8:   return "High priority"
    return "Review"

def priority_drivers(state: TrajectoryState) -> list:
    d = list(policy_for(state).drivers(state))
    if state.clinical_course:
        d.append(state.clinical_course)
    if state.resolution in ("unaddressed", "reopened"):
        d.append("unresolved across encounters")
    return d

def priority(state: TrajectoryState) -> int:   # ordinal score; NOT clinical risk
    return _priority_score(state)


def trajectory_change(prev, cur):
    if cur.resolution in ("resolved", "resolved_pending_confirmation"):
        return "resolved"
    if cur.evidence_relation() == "source_conflict":
        return "evidence_updated"
    if prev is None:
        return "stable"
    if ACTION_RISK.get(cur.action, 0) > ACTION_RISK.get(prev.action, 0):
        return "escalating"
    if ACTION_RISK.get(cur.action, 0) < ACTION_RISK.get(prev.action, 0):
        return "deescalating"
    return "stable"


def surface_question(state):
    # source_conflict outranks clinical resolution EVERYWHERE (our core rule):
    # the treatment may be settled while the RECORD still disagrees, so the
    # reconciliation task text must appear even when resolution == resolved.
    if state.evidence_relation() == "source_conflict":
        # name the conflicting entries but DON'T assert which is current — the
        # system flags, the clinician adjudicates (no verdict).
        entries = [e.assertion for e in state.evidence
                   if e.relation in ("support", "contradict", "not_assessable")]
        if len(entries) >= 2:
            listed = " and ".join(entries)
            return (f"The active record carries conflicting entries for the same "
                    f"medication thread or class — {listed}. Confirm which reflects "
                    f"the current regimen and remove the other before signing.")
        return ("The active record carries conflicting entries for the same medication "
                "thread or class. Confirm which reflects the current regimen and remove "
                "the other before signing.")
    if state.resolution in ("resolved", "resolved_pending_confirmation"):
        return None
    return policy_for(state).question(state)


def encounter_only_question(state):
    """BASELINE: what a single-encounter system (no cross-visit history) would ask."""
    if state.action == "discontinued":
        return "Are you still taking your controller inhaler?"
    if state.action == "self_reduced":
        return "Are you taking the controller inhaler as prescribed?"
    if state.action == "resumed":
        return "How are you doing on the controller inhaler?"
    return "Any changes to your medications?"
