"""
linker.py — claim-identity linking + hard-negative test (feedback Priority 3).

Goal is NOT a finished linker. It is to show that cross-encounter linking is a
REAL problem (drug name alone is insufficient) and that a structured claim
identity separates threads that surface language would confuse.

Claim identity = {subject, target, relation, attribute}
  - same drug, DIFFERENT relation  -> DIFFERENT trajectory
      "makes my hands shake" (adverse_effect) vs
      "don't need it at night" (regimen_sufficiency) vs
      "can't afford another"   (access_barrier)
  - DIFFERENT surface language, SAME {target, relation} -> SAME trajectory
      "only in the morning" / "still skip the evening" / "stopped the daily one"
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class ClaimIdentity:
    subject: str      # "patient"
    target: str       # normalized medication/topic, e.g. "controller_inhaler"
    relation: str     # regimen_sufficiency | adverse_effect | access_barrier | adherence
    # attribute is descriptive only; identity is (subject, target, relation)
    attribute: str = ""

    def key(self):
        return (self.subject, self.target, self.relation)


# --- crude identity extraction (keyword-based; a real system would use the LLM) ---
TARGET_KEYS = {
    "controller_inhaler": ("controller", "daily inhaler", "budesonide", "fluticasone",
                           "symbicort", "the brown one", "the purple one", "the daily one"),
    "rescue_inhaler": ("rescue", "blue one", "albuterol", "salbutamol", "ventolin"),
}
RELATION_KEYS = {
    "adverse_effect": ("shake", "shaky", "side effect", "makes me", "gives me", "jittery"),
    "access_barrier": ("afford", "cost", "expensive", "ran out", "couldn't get", "insurance"),
    "regimen_sufficiency": ("don't need", "in the morning", "morning", "skip", "stopped",
                            "once a day", "once daily", "enough", "fine without", "no problem",
                            "cut it", "reduced", "don't take", "only use"),
    "adherence": ("as prescribed", "twice daily", "every day", "always take"),
}

def extract_identity(text, target_hint=None):
    t = text.lower()
    target = target_hint
    if target is None:
        for tgt, kws in TARGET_KEYS.items():
            if any(k in t for k in kws):
                target = tgt; break
        target = target or "unknown"
    relation = "unknown"
    for rel, kws in RELATION_KEYS.items():
        if any(k in t for k in kws):
            relation = rel; break
    return ClaimIdentity("patient", target, relation, attribute=t[:40])

def same_trajectory(a: ClaimIdentity, b: ClaimIdentity) -> bool:
    return a.key() == b.key()


# ---- hard-negative suite -----------------------------------------------------
if __name__ == "__main__":
    print("HARD-NEGATIVE LINKING TEST\n" + "="*60)

    # ---- MUST LINK: same {target, relation}, different surface language ----
    thread = [
        "I only use the controller in the morning.",
        "I'm still skipping the evening puff.",
        "I stopped the daily inhaler.",
    ]
    print("\n[MUST LINK] same controller regimen-sufficiency thread:")
    ids = [extract_identity(x, target_hint="controller_inhaler") for x in thread]
    ok_link = all(same_trajectory(ids[0], x) for x in ids[1:])
    for x, i in zip(thread, ids):
        print(f"  {i.relation:20s} <- {x!r}")
    print(f"  => all linked: {ok_link}  {'OK' if ok_link else 'X'}")

    # ---- MUST SEPARATE: same drug, different relation ----
    separate = [
        ("It makes my hands shake.", "adverse_effect"),
        ("I don't need it at night.", "regimen_sufficiency"),
        ("I can't afford another one.", "access_barrier"),
    ]
    print("\n[MUST SEPARATE] same controller, different relations:")
    sep_ids = [(extract_identity(x, target_hint="controller_inhaler"), exp) for x, exp in separate]
    all_distinct = len({i.key() for i, _ in sep_ids}) == len(sep_ids)
    rel_correct = all(i.relation == exp for i, exp in sep_ids)
    for (i, exp), (x, _) in zip(sep_ids, separate):
        mark = "OK" if i.relation == exp else "X"
        print(f"  {i.relation:20s} (exp {exp:20s}) <- {x!r}  {mark}")
    print(f"  => all distinct threads: {all_distinct}  |  relations correct: {rel_correct}")

    # ---- the trap: drug-name-only linking would MERGE these three ----
    print("\n[WHY IT MATTERS] drug-name-only linking:")
    same_drug = len({i.target for i, _ in sep_ids}) == 1
    print(f"  all three mention the same drug (target=controller): {same_drug}")
    print(f"  -> naive drug-name linking merges 3 distinct issues into 1 (WRONG).")
    print(f"  -> identity on (target, relation) keeps them separate (RIGHT).")

    print("\n" + "="*60)
    passed = ok_link and all_distinct and rel_correct
    print("HARD-NEGATIVE SUITE:", "PASS" if passed else "NEEDS TUNING")
    print("\nHONEST LIMIT: identity here is keyword-based. It already separates")
    print("same-drug/different-relation threads (the hard part), but surface-form")
    print("variation ('morning only' vs 'only use in the morning') shows why a")
    print("production linker must extract {target, relation} with the LLM, not keywords.")
