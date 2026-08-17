# Sure for Sure portfolio acceptance contract

This contract defines the observable behavior of the medication-focused vertical
slice implemented by the top-level `pipeline/` package. The fixtures under
`tests/fixtures/acceptance/` are independently authored synthetic encounters. They
are not annotations of the organizer dataset and cannot support accuracy claims.

## Required execution path

`analyze_encounter` accepts one encounter, immutable source identity, and a provider
implementing the structured extraction protocol. The production path parses dialogue,
extracts and validates patient claims with exact spans, normalizes same-patient FHIR
medication evidence, links claims to that evidence, compares asserted fields, computes
CED, detects later resolution, routes and ranks actions, and builds the response.

Acceptance tests use `StubStructuredExtractionProvider` with schema-valid controlled
responses. `AnthropicStructuredExtractionProvider` is the selectable live adapter, but
no acceptance test requires credentials or network access. Missing credentials and
invalid provider output fail explicitly rather than silently producing zero claims.

## Locked behavioral cases

- **A — direct active claim:** metoprolol 100 mg every morning is active and its
  exact patient span is retained.
- **B — discontinuation:** “do not take … anymore” is stopped/discontinued,
  never active, and retains negation/discontinuation evidence.
- **C — contextual answer:** a patient short answer inherits lisinopril from the
  immediately relevant clinician turn, is active/daily, and cites both turns.
- **D — uncertainty:** the clinician supplies the medication; the patient supplies
  50 mg and explicit uncertainty. The result cannot be high confidence.
- **E — adherence gap:** active metformin with recurrent missed evening doses retains
  an adherence span and routes to `patient_clarification` when actionable.
- **F — later resolution:** one later claim establishes every disputed field of the
  earlier claim. Repeat patient clarification is suppressed, while remaining chart
  conflict can route to `chart_cleanup`.
- **G — unseen medication:** a medication present only in the fixture/provider response
  links dynamically to its FHIR resource without a production lexicon change.
- **H — no medication claim:** symptoms and scheduling alone yield no claims and no
  fabricated action.
- **I — multiple medications:** one patient turn yields separate claims with independent
  status and correctly delimited supporting evidence.
- **J — unresolved versus resolved conflict:** otherwise similar dose conflicts receive
  different resolution and routing; only the unresolved conflict asks the patient again.

## Evidence comparison

`EvidenceRelation` has exactly five public values:

- `support`: every linked, assessable observation for the asserted field accords with
  the normalized claim value.
- `contradict`: linked, assessable evidence exists and differs from the normalized claim
  value, with no matching source for that field.
- `silent`: the linked record does not state the asserted field, or no same-medication
  evidence is linked. Silence is not positive support.
- `not_assessable`: a defensible field comparison cannot be formed. This is distinct
  from a record that can be inspected but does not state the asserted value.
- `source_conflict`: linked record sources contain incompatible values, including a mix
  of observations that accord with and contradict the claim.

Only fields asserted by the patient claim are compared. A patient-unasserted dose,
frequency, route, unit, or status does not become missing support. Normalization used
for claims and records is deterministic and shared by the comparison stage.

### Field-to-claim aggregation

The overall claim relation is computed from the emitted field comparisons with this
precedence:

1. no comparisons → `not_assessable`;
2. any `source_conflict` → `source_conflict`;
3. otherwise any `contradict` → `contradict`;
4. otherwise any `not_assessable` → `not_assessable`;
5. otherwise any `silent` → `silent`;
6. all comparisons are `support` → `support`;
7. any unrecognized remainder → `not_assessable`.

`disputed_fields` contains every asserted field whose field relation is not `support`.
Supporting and conflicting evidence IDs remain visible in the response.

## CED semantics

CED is the versioned product of the claim-confidence signal and record-divergence
signal. `ced-v1` uses confidence values `emphatic=1.0`, `neutral=0.67`,
`hedged=0.33`, and `unclear=None`; divergence values are `support=0.0`,
`silent=0.5`, `source_conflict=0.75`, `contradict=1.0`, and
`not_assessable=None`. If either input is `None`, the claim is unscorable and includes
an abstention reason.

Confidence is derived deterministically from grounded patient-language cues, not from
claim specificity, field completeness, or chart evidence. A hedge alone is `hedged`, a
booster alone is `emphatic`, both together are `neutral`, and hesitation/evidential/no
cues are `neutral`. Patient `...` and `…` are preserved as hesitation cues but do not
lower confidence by themselves; bracketed editorial ellipses are ignored.

CED is an interpretable prioritization heuristic. It is not a calibrated probability,
clinical-risk score, diagnostic confidence, or assertion that the chart is more
truthful than the patient. Resolution does not rewrite the historical CED inputs.

## Resolution semantics

Resolution uses the **single-claim model** represented by the singular
`resolving_claim_id`. A candidate must be a later, patient-grounded claim for the same
normalized medication, have at least the original claim's confidence level, and make a
neutral or emphatic current-regimen assertion.

A disputed field is materially established only when that candidate asserts the field
and its own field comparison has a chart-consistent value. A repeated conflicting value
does not resolve a discrepancy merely because the field was mentioned. In a
`source_conflict`, a candidate value that accords with at least one normalized record
value may establish the patient-side field while `chart_conflict_remaining` stays true.

One later candidate must establish every disputed field for `resolved=true`. The first
eligible complete candidate in transcript order becomes `resolving_claim_id`. If none
is complete, partial fields are taken from one deterministic best candidate only—the
candidate establishing the most disputed fields, with transcript order and claim ID as
tie breakers. Fields from separate partial candidates are never unioned.

For every `ResolutionResult`, `resolved_fields` and `unresolved_fields` are disjoint and
partition `disputed_fields`. A resolved result has at least one disputed field and no
unresolved fields. An unresolved result with disputed fields retains at least one
unresolved field. The rationale names the same candidate used for field bookkeeping and
never emits an empty unresolved-field list.

## Routing and ranking

`ActionRoute` has exactly four public values: `patient_clarification`,
`chart_cleanup`, `clinician_review`, and `no_action`. Stage 08 applies these conditions
in order:

1. a resolved claim routes to `chart_cleanup` when `chart_conflict_remaining` is true,
   otherwise `no_action`;
2. a later claim that resolves another claim and itself has `source_conflict` routes to
   `no_action`, because the earlier action owns the remaining chart cleanup;
3. an adherence gap routes to `patient_clarification`;
4. `support` routes to `no_action`;
5. `not_assessable` routes to `clinician_review`;
6. an emphatic `source_conflict` with supporting evidence routes to `chart_cleanup`;
7. remaining `contradict`, `source_conflict`, and `silent` results route to
   `patient_clarification`;
8. the defensive fallback is `clinician_review`.

Every action includes the claim, divergence, resolution, recommendation, routing
rationale, and unchanged CED score. Stage 09 ranks only actionable, scorable items by
descending CED, then claim ID. Unscorable and `no_action` items have no rank.

## Response and provenance

`EncounterAnalysis` exposes summary counts, turns, claims, record evidence, links,
divergences, CED results, resolutions, and actions. Summary route counts use the same
four route names above.

Every encounter output retains source dataset/file, record ID, record index, source
hash, and record hash when source provenance is provided. Claims retain exact
transcript turn/character spans and extractor metadata. Linked FHIR evidence retains
resource ID and source path. For every span, slicing the original transcript from
`start_char` to `end_char` equals `text` exactly.

## Anti-memorization contract

Production source must not contain organizer record IDs, copied full organizer
transcript lines, branches on source record ID/index, constant `get_by_index` selection,
output dictionaries keyed by organizer encounters, or a medication inventory derived
from the 25 records. The locked static tests enforce mechanically detectable portions
of this restriction.

## Executable acceptance criteria

- `python -m pytest tests/acceptance -q` passes the locked independently authored cases
  and provenance/static-integrity checks.
- `python -m pytest tests/unit/test_divergence_aggregation.py -q` verifies asserted-field
  comparison and relation aggregation.
- `python -m pytest tests/unit/test_resolution_fields.py -q` verifies single-claim field
  bookkeeping, chart-consistent resolution, and model invariants.
- `python -m pytest tests/regression/test_ced_semantics_v2.py -q` verifies stable CED and
  resolution-sensitive routing.
- `python -m pytest -q` passes the complete credential-free suite.
- When the organizer dataset is present locally, the guarded integration checks run all
  25 encounters without schema failure. This operational check is not an accuracy
  measurement.
- No accuracy claim is made without independently reviewed gold data.
