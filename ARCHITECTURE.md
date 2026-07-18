# Architecture (post-refactor)

## What this system is (and isn't)

By Anthropic's framework (*Building Effective Agents*), agentic systems split into
**workflows** (LLMs/tools orchestrated through predefined code paths) and **agents**
(LLMs dynamically directing their own tool use). **This is a workflow, not an agent —
specifically a *Routing* workflow** — and that is a deliberate choice: clinical safety
needs the predictability and auditability a workflow gives, not autonomous model-driven
decisions on what to suppress or surface.

Pattern mapping:
- **Routing** — `disposition()` classifies each divergence and routes it to a
  specialized path: `ask_patient` / `suppress` / `verify_current_regimen`.
  (The doc notes routing works when classification is accurate "either by an LLM or a
  more traditional classification model/algorithm" — ours is deterministic rules.)
- **Prompt chaining + gate** — extraction → certainty grade → 3-gate candidacy →
  routing. The gates are the programmatic checks that keep the chain on track.

LLM is used only for **language interpretation** (claim extraction, certainty grading,
follow-up generation). Every **safety decision** (what diverges, what to suppress, how
to rank) is deterministic — so each decision is auditable. This is the differentiator
from delegating calculation to an LLM.

*Next step toward a true agent:* when evidence is insufficient to judge a divergence,
let the system decide **which record to pull next** (dynamic tool use). That is the one
place the step count isn't predictable — i.e. where an agent, not a workflow, fits.

## Layering
```
evidence.py     EvidenceItem + evidence_relation()   — the ONE definition of how
     │                                                  record evidence combines
     ▼                                                  (was duplicated in the scorer;
policy.py       DomainPolicy per domain                 the two had drifted)
     │          POLICY = {medication, symptom, ...}   — per-domain risk/question/
     ▼                                                  drivers/routing/silent_drift
trajectory.py   TrajectoryState + neutral engine        in ONE place (was `if domain==`
                                                         scattered across the engine)
                                                       — divergence(), disposition(),
                                                         priority_*, carry_forward();
                                                         domain-neutral, looks up
                                                         policy_for(state).
```

## What the refactor fixed
1. **One `evidence_relation`.** Lives in `evidence.py`; both the engine and the
   `extract_events.py` scorer import it. They previously drifted (only the scorer
   treated an undated field as older); the shared version keeps that correct rule.
   `trajectory.py`'s method is a thin wrapper, not a second definition.
2. **Data-driven domains.** All per-domain behavior — risk scoring, question text,
   drivers, ask-routing, and the `silent_drift` rule — lives in `policy.py`. The
   engine has **zero** `domain ==` branches. `medication` and `symptom` are both
   `DomainPolicy` instances (symptom overrides risk/question/drivers/wants_ask and
   sets `allows_silent_drift = False`).
3. **Dead lineage archived.** `res0216_extract_v2.py`, `res0216_pipeline.py`,
   `grade_test.py` → `archive/` (superseded; off the live path).

## Live demo path
`run_trajectory.py --mock` → `adapter.py` → `trajectory.py` (+ evidence, policy).
Nothing on this path imports the archived files.

## Adding a new divergence domain
1. Subclass `DomainPolicy` in `policy.py`, override `risk/question/drivers/wants_ask`
   (and `allows_silent_drift` if needed).
2. Add it to the `POLICY` dict.
3. Set `state.domain = "yourdomain"`. **No edits to `trajectory.py`.**

## Verified invariants (unchanged by refactor)
- oracle: ALL ANSWER-KEY ASSERTS PASS
- safety: 10/10 field checks, 3/3 high-risk false-suppression kept open
- runner: medication branches A/B/C + symptom branch D, identical tiers/dispositions
- engine domain branches: 0


## decision_history.py
Thin ablation wrapper over the engine: removes each past encounter and re-runs the
existing routing to find which visits actually change the current decision. No engine
logic changes.
