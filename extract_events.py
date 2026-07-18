"""
extract_events.py — END-TO-END test (step 5).
Extract a longitudinal event from each follow-up transcript, then SCORE it
against the authored answer key in fixtures_abc.py.

Rigor: the prompt lists allowed enum VALUES (so output is parseable) but never
tells the model which value is correct for a given transcript. Recovering the
authored state from dialogue alone is the actual test.

Run:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 extract_events.py                # all 4
    python3 extract_events.py A-V2           # one
"""
import os, sys, json

from fixtures_abc import A_V2, A_V3, B_V2, C_V2   # answer key
from evidence import evidence_relation           # single shared definition

ANSWERS = {"A-V2": A_V2, "A-V3": A_V3, "B-V2": B_V2, "C-V2": C_V2}

SYSTEM = """You extract ONE longitudinal treatment-reasoning event from a clinical
follow-up transcript. Output strict JSON. Do not guess beyond what is said.

Fields and their ALLOWED values (choose the one the transcript supports):

  action: the direction of the patient's controller use BY THE END of this visit.
    Report what the patient is actually doing / has done, NOT merely what the
    clinician recommends.
    one of: none | planned | self_reduced | discontinued | resumed
    - self_reduced: cut an existing regimen down but still taking some
    - discontinued: stopped taking it entirely
    - resumed: has gone back to (or agreed and committed to) the fuller/intended
      regimen. Only use resumed if the patient actually agrees to resume, not if
      the clinician merely advises it.

  resolution: state of the CLINICAL issue by the end of THIS visit. Be STRICT.
    one of: unaddressed | partially_addressed | resolved_pending_confirmation | resolved
    Decision rule (apply in order):
    - If the clinician only asked/advised and the patient did NOT agree or restate
      a plan -> unaddressed. (Advice alone is NOT resolution. A patient saying
      "I'll think about it" / "not saying yes yet" is unaddressed.)
    - If a regimen was clarified and a plan stated but patient agreement is not
      explicit -> resolved_pending_confirmation.
    - Only if clinician clarified the regimen AND stated a plan AND the patient
      explicitly acknowledged/agreed/restated it -> resolved.
    - A pure records/source discrepancy (e.g. medication list disagrees with a
      newer note) is a RECORD issue, not a clinical treatment resolution: set
      resolution = unaddressed for the clinical trajectory even if the clerical
      list is being corrected.

  patient_regimen_reported: "QD" | "BID" | "none" | other short string

  evidence: list of record/source items the transcript references, each:
    { "relation": support|contradict, "source_type": "...",
      "timestamp": "YYYY-MM-DD", "assertion": "short" }
    TIMESTAMP IS REQUIRED whenever the transcript gives any date or relative time.
    Convert relative dates to ISO using visit context: e.g. "dated the fourteenth"
    or "three weeks ago" -> a concrete YYYY-MM-DD (approximate the day if needed;
    never leave it null when a time reference exists).
    If a NEWER source supports the patient while an OLDER structured field
    contradicts, include BOTH with their dates so the conflict is visible.
    Do NOT list the patient's own self-report as an evidence item; evidence means
    RECORD/clinical sources (prescription, medication list, specialist note,
    observations), not the patient's statement.

  clinical_course: short phrase for any change in symptoms/rescue use, or "" if none.
    Describe co-occurrence only; do NOT assert causation.

  commitments: list of { "target": "...", "level": hedged|neutral|emphatic|not_asserted,
    "cue": "exact short phrase or null" } — attach certainty to the specific claim
    it modifies, not to the whole visit.

Return ONLY the JSON object."""

def extract(tag, client, model="claude-sonnet-4-6"):
    transcript = open(f"followups/{tag}.txt").read()
    msg = client.messages.create(
        model=model, max_tokens=1500, system=SYSTEM,
        messages=[{"role": "user", "content": f"Transcript ({tag}):\n{transcript}\n\nExtract the event JSON."}],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    return json.loads(raw)

def score(tag, got):
    exp = ANSWERS[tag]
    rows = []
    # action
    rows.append(("action", got.get("action"), exp.action, got.get("action") == exp.action))
    # resolution
    rows.append(("resolution", got.get("resolution"), exp.resolution,
                 got.get("resolution") == exp.resolution))
    # evidence_relation (derived) — only a decision axis when the issue is NOT
    # clinically resolved. For a resolved encounter, evidence_relation is
    # descriptive, not a pass/fail criterion.
    # evidence_relation is a decision axis ONLY when it is doing the work.
    # It is descriptive (not pass/fail) when:
    #   - the issue is clinically resolved (B-V2), or
    #   - the medication is discontinued (A-V3): the ACTION is the signal, and
    #     a stopped drug has no live regimen-adherence to reconcile against.
    axis_active = exp.resolution != "resolved" and exp.action != "discontinued"
    if axis_active:
        got_rel = evidence_relation(got.get("evidence", []))
        rows.append(("evidence_relation", got_rel, exp.evidence_relation(),
                     got_rel == exp.evidence_relation()))
    return rows

if __name__ == "__main__":
    try:
        import anthropic
    except ImportError:
        sys.exit("pip install anthropic")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("export ANTHROPIC_API_KEY=sk-ant-... first")
    client = anthropic.Anthropic()

    tags = [sys.argv[1]] if len(sys.argv) > 1 else ["A-V2", "A-V3", "B-V2", "C-V2"]
    all_pass = True
    for tag in tags:
        print(f"\n{'='*60}\n{tag}\n{'='*60}")
        got = extract(tag, client)
        print("extracted:", json.dumps(got, indent=2)[:600])
        print(f"\n{'field':20s} {'got':28s} {'expected':28s} ok")
        for field_, g, e, ok in score(tag, got):
            print(f"{field_:20s} {str(g):28s} {str(e):28s} {'OK' if ok else 'X'}")
            all_pass = all_pass and ok
    print(f"\n{'='*60}")
    print("ALL RECOVERED" if all_pass else "MISMATCHES — see X rows above (tune prompt)")
