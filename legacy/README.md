# Sure for Sure

**Turning isolated clinical conversations into a longitudinal work queue** — what
needs to be asked, what belongs in record reconciliation, and what should be
suppressed because it was already resolved.

Built for the Abridge × Anthropic × Lightspeed *Future of Agentic AI in Healthcare*
hackathon (July 2026).

---

## What it does

Ambient scribes capture *what was said* in one encounter. They don't track whether
a patient's **treatment reasoning** — the decisions, confidence, and actions they
express about their own care — diverges from the record, or whether that divergence
**persists, resolves, or worsens across visits**.

Sure for Sure sits on top of an ambient scribe and, for each finding, decides one thing:

| Route | When | Output |
|-------|------|--------|
| `ask_patient` | a live clinical divergence | one targeted question for the next visit |
| `verify_current_regimen` | records disagree with each other | a medication-reconciliation task |
| `suppress` | already resolved | nothing — actively withheld to avoid alert fatigue |



**Decision-changing history.** Most chart-aware systems summarize the past. Sure for Sure asks a sharper question: *which* past encounters actually change the next clinical action? It re-runs its own routing with each past visit removed (`decision_history.py`) — surfacing the history that moves the decision and leaving the rest out of the clinician's view. History doesn't just add context; it changes which question is worth asking.

It never issues a verdict. It surfaces a question or a record task; clinical
judgment stays with the clinician. Certainty is estimated from language, never
asserted as true belief.

## Why it's a *workflow*, not a chatbot

By Anthropic's *Building Effective Agents* framing, this is a **Routing workflow**,
not an autonomous agent — a deliberate choice: clinical safety needs the
predictability and auditability a workflow gives. The LLM is used only for
**language interpretation** (claim extraction, certainty grading); every **safety
decision** (what diverges, what to suppress, how to rank) is deterministic and
auditable. See `ARCHITECTURE.md`.

## Architecture

**Core engine** (deterministic, no LLM):
```
evidence.py         the one definition of how record evidence combines
policy.py           per-domain divergence policy (medication, symptom, ...)
trajectory.py       domain-neutral engine: divergence, disposition, priority, suppression
decision_history.py ablation: which past visits actually change the decision
```

**Inputs & routing:**
```
adapter.py          bridges single-encounter candidates + extracted events into one schema
fhir_competition.py parses the hackathon FHIR; detects duplicate/stale meds (case 1)
fhir_record.py      parses Synthea FHIR via refill inference (case 2 record half)
extract_events.py   LLM step: dialogue -> claims/certainty (the only place Claude runs)
```

**App & demo:**
```
app.py              custom Flask web app — feed an encounter, the pipeline runs live
analyze.py          the analysis core app.py calls
sure_demo.html      two-encounter demo UI (Howell #10, John RES0216)
run_trajectory.py   CLI: the full longitudinal story end to end (--mock needs no key)
```

**Validation & method tooling:**
```
fixtures_abc.py        authored answer key + oracle asserts
safety_eval.py         field checks + false-suppression suite
res0216_end2end.py     single-encounter extraction pipeline for the John case
res0216_extract_v3.py  its two-pass extractor
gen_followups.py       state-first transcript synthesis (labels hidden from the model)
linker.py              claim-identity linking + hard-negative test (documents a real limit)
```

Full layering and the "how to add a domain" recipe are in `ARCHITECTURE.md`.

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env   # then add your ANTHROPIC_API_KEY (only needed for the LLM steps)

# the longitudinal engine over the demo trajectory (+ live competition parse):
python3 run_trajectory.py --mock

# the web app (pick an encounter, engine runs live):
python3 app.py        # then open http://127.0.0.1:5000

# validation:
python3 fixtures_abc.py     # oracle: policy correctness
python3 safety_eval.py      # 10/10 field checks, 3/3 false-suppression kept open
```

## Data

This repo contains **code only**. The data it runs on is referenced, not redistributed:

- **Competition data** (`synthetic-ambient-fhir-25.jsonl`): provided by the
  organizers *for use during the hackathon*. **Not included in this repo.** To run
  the competition case, place the file where `app.py` / `fhir_competition.py` expect
  it (see `SURE_DATA` / the default path in those files).

- **RES0216 transcript** (case 2, real de-identified clinical speech): from
  [chicago-aiscience/Clinical_KG_OS_LLM](https://github.com/chicago-aiscience/Clinical_KG_OS_LLM),
  **BSD-3-Clause**. **Not redistributed here** — download it from the source repo
  and place it at `data/RES0216.txt` to reproduce case 2. Short verbatim excerpts
  that appear in the demo UI / fixtures are attributed inline to this source.

- **Synthetic FHIR record** for case 2: the refill pattern is *referenced* from a
  Synthea artifact (Pearl430, ~371-day refill gap). Parameters live in code
  (`run_trajectory.py`, `V1_META`), not as a bundle file. Synthea is open-source
  (Apache-2.0).

## Honest scope

- A technically-structured prototype with deterministic longitudinal policy and
  controlled extraction checks — **not** an accuracy-validated clinical model.
- Case 2's speech (RES0216) and its synthetic FHIR record are **different
  individuals** by construction; stated openly, not hidden.
- The keyword linker separates relations but misses surface-form variation;
  production identity resolution would use the LLM.
- Refill-derived consumption is a **secondary** signal, not a proven rate.

## License

Code in this repo: MIT (see `LICENSE`). Third-party data is under its own license
as noted above and is not redistributed here.
