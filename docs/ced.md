# CED

CED is claim-specific confidence multiplied by divergence from the available medical
record. The current version is `ced-v1`.

| Confidence | Score |
|---|---:|
| emphatic | 1.00 |
| neutral | 0.67 |
| hedged | 0.33 |
| unclear | abstain |

## Confidence semantics v2

Confidence represents the patient's linguistic commitment to the claim. Claude returns
typed, verbatim cue quotes from patient supporting speech; Python grounds those quotes
and derives the level deterministically. The cue types are `booster`, `hedge`,
`hesitation`, `self_justification`, and `authority`.

An invalid, misclassified, or out-of-span confidence cue is discarded and recorded as a
claim-level validation warning. It does not invalidate otherwise grounded claim evidence.
Confidence is derived from the remaining valid cues and defaults to `neutral` if none
remain. Invalid claim supporting evidence remains a hard source-grounding failure.

- Boosters are explicit forms such as “always,” “never,” “definitely,” “for sure,”
  “I know,” “100%,” and “no problems at all.”
- Hedges are explicit forms such as “maybe,” “I think,” “I guess,” “not sure,” “could
  be,” “probably,” “I don't know,” and “I'm uncertain.”
- A hedge alone is `hedged`; a booster alone is `emphatic`; both together are `neutral`.
- Hesitation or evidential cues alone are `neutral`. No cues is an ordinary `neutral`
  assertion.
- `...` and `…` are detected within patient supporting spans as hesitation. Bracketed
  editorial omissions such as `[ ... ]` are ignored.

Specificity, completeness, chart support, and chart conflict never raise or lower this
confidence signal. Frequency or continuity phrases such as “every day,” “daily,”
“still,” and “each time” are not boosters. “A couple of years,” “really,” “a little,”
and “kind of” are not hedges by themselves.

| Record relation | Score |
|---|---:|
| support | 0.00 |
| silent | 0.50 |
| source conflict | 0.75 |
| contradict | 1.00 |
| not assessable | abstain |

If either axis abstains, CED is `null`. The item can still route to clinician review; it
never receives a fabricated score. Actionable scored items sort by CED descending with a
deterministic claim-ID tie-break. Routing creates no second numeric priority.

CED ranks attention. It is not clinical risk, chart truth, or the probability of patient
error. The weights are versioned prototype heuristics and are not clinically validated.
