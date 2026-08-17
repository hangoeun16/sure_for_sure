# Input format

Each JSON object must contain exactly these top-level fields:

```json
{
  "id": "...",
  "metadata": {},
  "patient_context": {},
  "encounter_fhir": {},
  "transcript": "DR: ...\nPT: ...",
  "note": "...",
  "after_visit_summary": "...",
  "after_visit_summary_provenance": {}
}
```

The boundary deliberately validates only organizer-compatible top-level structure. Stage
03 inspects the nested medication fields it consumes rather than attempting to reproduce
FHIR R4 in Pydantic.

JSON files may contain one object or an array. JSONL files contain one object per nonblank
line. Use `python tools/validate_input.py PATH` for validation.

`metadata.claim_extraction` is reserved for credential-free public examples and fixtures;
the live Anthropic provider ignores it.
