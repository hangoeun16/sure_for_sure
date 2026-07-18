"""
policy.py — per-domain divergence policy, in ONE place.

Before: adding a domain (medication → symptom → followup) meant threading an
`if domain == "..."` branch through disposition(), _priority_score(),
surface_question(), and priority_drivers() — four edits per domain, easy to miss one.

Now: each domain is a single DomainPolicy entry. The engine is domain-neutral and
looks up POLICY[state.domain]. Adding a domain = adding one entry here.

A policy answers four questions for a given state:
  - risk(state)      -> int   contribution to the ordering score (pre-resolution)
  - question(state)  -> str   the clarifying question text (or None)
  - drivers(state)   -> list  human-readable reasons for the priority
  - disposition_hint -> the domain's natural routing when nothing higher applies
"""
from evidence import evidence_relation

# shared ordering weights (NOT calibrated clinical risk — prototype ordering only)
ACTION_RISK     = {"none": 0, "planned": 1, "self_reduced": 2, "resumed": 1, "discontinued": 3}
RESOLUTION_OPEN = {"unaddressed": 2, "partially_addressed": 1, "reopened": 2,
                   "resolved_pending_confirmation": 0, "resolved": 0}
COMMIT_BONUS    = {"hedged": 0, "neutral": 0, "unclear": 0, "not_asserted": 0, "emphatic": 1}


class DomainPolicy:
    """Base = medication behavior. Other domains subclass and override."""
    disposition_hint = "monitor"
    allows_silent_drift = True     # a stopped pill can "silently drift"; a symptom cannot

    def risk(self, state) -> int:
        return ACTION_RISK.get(state.action, 0) * 3

    def question(self, state):
        rel = evidence_relation(state.evidence)
        if state.action == "discontinued":
            return ("The controller was reduced across visits and then stopped, while "
                    "nighttime symptoms and rescue use increased over the same period. "
                    "What led from reducing it to stopping, and how has breathing changed?")
        if state.action == "self_reduced":
            return ("Patient is confident the reduced once-daily regimen is sufficient. Was "
                    "the step-down reviewed with a clinician, or self-directed?")
        return None

    def drivers(self, state) -> list:
        d = []
        if state.action == "self_reduced":  d.append("self-directed medication reduction")
        if state.action == "discontinued":  d.append("medication discontinued")
        return d

    def wants_ask(self, state) -> bool:
        return state.action in ("self_reduced", "discontinued")


class SymptomPolicy(DomainPolicy):
    """Risk is carried by a CONTRADICTING record finding, not a medication action.
    A confident 'I'm fine' against a worsening result is the miss to prevent."""
    disposition_hint = "monitor"
    allows_silent_drift = False

    def risk(self, state) -> int:
        return 8 if evidence_relation(state.evidence) == "contradict" else 0

    def question(self, state):
        if evidence_relation(state.evidence) in ("contradict", "source_conflict"):
            return ("Patient reports feeling well, but recent findings suggest the "
                    "condition may be worsening. Confirm current symptoms against "
                    "the latest results before relying on the patient's impression.")
        return None

    def drivers(self, state) -> list:
        if evidence_relation(state.evidence) == "contradict":
            return ["reassuring self-report contradicts worsening findings"]
        return []

    def wants_ask(self, state) -> bool:
        return evidence_relation(state.evidence) == "contradict"


POLICY = {
    "medication": DomainPolicy(),
    "symptom":    SymptomPolicy(),
}

def policy_for(state):
    return POLICY.get(state.domain, POLICY["medication"])
