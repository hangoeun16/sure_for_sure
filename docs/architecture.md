# Architecture

The repository mirrors the product decision path. Infrastructure loads and validates an
encounter before the numbered reasoning pipeline begins.

```text
EncounterInput
  01 parse dialogue
  02 extract patient claims and claim-specific confidence
  03 extract same-patient record evidence
  04 link claims to evidence
  05 score field-level and overall divergence
  06 compute CED
  07 detect later patient-confirmed resolution
  08 route remaining uncertainty
  09 rank actionable, scorable work by CED
  10 build structured clinician report
```

`pipeline/runner.py` calls these stages directly. Stages join through `claim_id` in one
typed `PipelineState`; neither the API nor CLI contains clinical reasoning.

## Deterministic and interpretive boundaries

Stage 02 is the language interpretation boundary. The Anthropic adapter returns a typed
claim proposal; Python then validates every quote, patient-grounded span, confidence cue,
and schema field. Stages 01 and 03–10 are deterministic.

`pipeline/evidence.py` is the only evidence-combination implementation. A supporting and
contradicting record entry becomes `source_conflict`; absence becomes `silent`, never a
contradiction. `pipeline/ced.py` owns all numeric mappings.

Resolution never overwrites historical divergence or CED. It changes who still owns the
work. A patient question can be suppressed while a chart-cleanup action remains.

## Interfaces

`backend/repository.py` reads JSON or JSONL and produces immutable source hashes. FastAPI
and the CLI both invoke `run_pipeline`. The React client consumes the structured report;
it does not recompute evidence, CED, resolution, routes, or ranks.

The organizer dataset has one encounter per patient, so it cannot validate longitudinal
behavior empirically.
