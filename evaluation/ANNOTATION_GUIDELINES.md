# Organizer medication annotation guidelines

This evaluation set covers every one of the 25 organizer-provided synthetic
encounters. It is an author-annotated engineering evaluation set, not independently
validated clinical ground truth.

## Inclusion

- Include medication claims spoken or explicitly confirmed by the patient.
- A short patient answer may use the immediately preceding clinician or nurse turn
  for medication identity and regimen context.
- Include starts, current use, stopped use, possession, and adherence gaps.
- Exclude clinician-only, nurse-only, and family-only statements.
- Do not manufacture a medication identity from a generic statement such as
  "nothing regular" or "the headache stuff."
- Keep a contextual confirmation even when the patient is unsure which item does
  what; label that claim `unclear` and preserve the uncertainty cue.

## Fields and evidence

- `span` contains a zero-based dialogue turn index and a verbatim substring of that
  patient turn. It is validated against the source transcript before evaluation.
- Fields are annotated only when stated by the patient or grounded by the local
  question/instruction that the patient explicitly confirms.
- `relevant_evidence_paths` identifies same-patient FHIR or longitudinal-medication
  entries that a correct linker should retrieve. An empty list means the supplied
  record has no medication evidence for that claim.
- `expected_relation` applies the product rule: every patient-asserted comparable
  field must be supported for overall `support`; unverifiable asserted fields yield
  `silent`; direct disagreement yields `contradict`; competing record values yield
  `source_conflict`.

## Provenance

The annotations were written during the corrective engineering pass on 2026-08-06
after reading all 25 transcripts and their supplied FHIR/longitudinal medication
data. Record IDs and exact short quotes are retained solely to make evaluation
auditable; the full organizer transcripts are not copied into this repository file.
