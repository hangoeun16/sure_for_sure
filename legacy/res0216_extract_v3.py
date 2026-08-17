"""
Stage 1 — 2-PASS extraction for RES0216.

Fixes the v1 bug where "always" (confidence) landed on the TRUE claim
("takes daily med") instead of the CONTRADICTED one (adherence / QD-vs-BID).

  Pass 1  : extract the claims the patient COMMITS TO in context. No modality.
            "I always take it" (asked about adherence) -> an ADHERENCE claim,
            not a literal "takes a daily medication". Confident summaries and
            their qualifying details are emitted as SEPARATE claims so the
            conflict surfaces at record comparison.
  Pass 2  : for ONE claim at a time, extract certainty cues found in THAT span.
            Isolation prevents a cue from attaching to the wrong claim.
  Guardrail: drop any cue whose token isn't literally in the claim's span.

Run:
    export ANTHROPIC_API_KEY=sk-ant-...     # no smart quotes
    pip install anthropic
    python3 res0216_extract_v2.py
"""

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Cue:
    type: str
    token: str

@dataclass
class Claim:
    utterance_id: str
    text: str
    speech_act: str
    claim: str
    target_resource: Optional[str]
    cues: list = field(default_factory=list)


TRANSCRIPT = """
[P-17] I just use the one that I take every day. I don't really use the as-needed
one because I just haven't had to in a really long time so I didn't refill my last one.
[P-18] it's been a couple of years since I needed that, but I still take the daily one.
[P-19] No, I always take it. I'm supposed to actually take it morning and night, but
for a while sometimes I was skipping the night one because I didn't feel that I was
needing it. So lately I've been taking it everyday, but just in the morning.
[P-20] I haven't needed the rescue one in a few years and even when I was just taking
it in the morning, I haven't had any problems.
[P-24] I have high blood pressure, I don't really see my doctor very much, I just am on medication.
[P-25/26] I take the salbutamol, and I take Ramipril.
""".strip()


PASS1_SYSTEM = """You extract record-verifiable claims a patient COMMITS TO. In this \
pass do NOT score confidence and do NOT list certainty words — only identify the claims.

Read for what the patient is actually asserting IN CONTEXT, not the literal surface.
Example: when asked about adherence, "I always take it" is a claim about ADHERENCE \
("is fully adherent to the controller regimen"), NOT merely "takes a daily medication". \
Capture the committed meaning, because that is what may conflict with the record.

When one utterance holds BOTH a confident self-assessment AND a qualifying detail \
(e.g. "I always take it, but just in the morning"), emit them as SEPARATE claims:
  - the committed self-assessment  -> "is adherent to the controller regimen"
  - the concrete factual detail    -> "takes the controller once daily, mornings only"
so that any conflict between them can surface later at record comparison.

For each claim output an object:
  utterance_id    : the [P-n] tag
  text            : the exact source span (verbatim)
  claim           : normalized paraphrase of the COMMITTED meaning
  speech_act      : "assertion" | "worry" | "hypothesis" | "question"
  target_resource : slug you choose (controller-inhaler | rescue-inhaler |
                    bp-medication | hypertension-diagnosis ...), or null

Return ONLY a JSON array. No prose, no markdown, no code fences."""


PASS2_SYSTEM = """You are given ONE claim and its source text span. List ONLY the \
certainty cues present IN THIS SPAN that modify THIS claim. Do not infer cues from \
outside the span.

DECISIVE TEST for whether a word is a cue at all:
  Remove the word. If a FACT changes, it is plain description, NOT a cue.
  If only the speaker's DEGREE OF CONFIDENCE changes, it is a cue.
  - "I take it every day"      -> remove "every day": the frequency fact is lost.
                                  => "every day" is DESCRIPTION, not a cue. Emit nothing.
  - "I always take it [as directed]" -> remove "always": the adherence claim remains,
                                  only its emphasis is lost. => "always" is a BOOSTER.

cue types:
  booster            : speaker loads EXTRA CONFIDENCE onto their own judgement.
                       YES: always, never, definitely, for sure, no problems at all,
                            I know, 100%
                       NO (do not tag): every day, everyday, still, daily, each time
                            -- these state frequency/continuation, not confidence.
  hedge              : genuine uncertainty markers.
                       YES: maybe, I think, I guess, not sure, could be, probably
                       NO (do not tag): approximations and fillers like "a couple of
                            years", "really", "kind of", "a little" -- not uncertainty.
  self_justification : an experiential REASON the patient offers to BACK their own
                       confidence ("haven't needed it in years", "didn't feel I needed
                       it", "it's been fine"). A reason, not an intensifier. Not a booster.
  authority          : attributes the claim to an outside source
                       ("the doctor said", "I'm supposed to", "I read online").

Additional rules:
  - token must be a SHORT phrase (a few words), never a whole clause. If the only
    match is a long clause, the cue is likely absent -- emit nothing.
  - a claim may legitimately have NO cues. Empty list is the correct, common answer.

Each cue: {"type": ..., "token": "<exact short phrase copied from the span>"}.
Return ONLY a JSON array. No prose, no fences."""


def _client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ANTHROPIC_API_KEY not set. Run: export ANTHROPIC_API_KEY=sk-ant-...")
    if not key.isascii():
        sys.exit("API key has non-ASCII chars (smart quotes?). Re-export with plain quotes.")
    try:
        import anthropic
    except ImportError:
        sys.exit("pip install anthropic")
    return anthropic.Anthropic()


def _json_call(client, system, user, model="claude-sonnet-4-6", max_tokens=2000):
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    return json.loads(raw)


def pass1_claims(client):
    data = _json_call(client, PASS1_SYSTEM, f"Transcript:\n{TRANSCRIPT}\n\nExtract the committed claims.")
    return [Claim(
        utterance_id=d.get("utterance_id", "?"),
        text=d.get("text", ""),
        speech_act=d.get("speech_act", "assertion"),
        claim=d.get("claim", ""),
        target_resource=d.get("target_resource"),
    ) for d in data]


def pass2_cues(client, claim: Claim):
    user = f'Claim: "{claim.claim}"\nSource span: "{claim.text}"\n\nList the certainty cues in this span.'
    data = _json_call(client, PASS2_SYSTEM, user, max_tokens=500)
    cues = []
    span_lower = claim.text.lower()
    for c in data:
        token = c.get("token", "")
        # guardrail 1: token must literally appear in this claim's span
        # guardrail 2: a cue is a short phrase, not a whole clause (<= 6 words)
        if not token or token.lower() not in span_lower:
            print(f"    [dropped: not in span] {c.get('type')}:{token!r}")
        elif len(token.split()) > 6:
            print(f"    [dropped: too long to be a cue] {c.get('type')}:{token!r}")
        else:
            cues.append(Cue(c.get("type", ""), token))
    return cues


if __name__ == "__main__":
    client = _client()
    print("=== Stage 1 (2-pass) extraction — RES0216 ===\n")

    print("--- Pass 1: committed claims (no modality yet) ---")
    claims = pass1_claims(client)
    for c in claims:
        print(f"  [{c.utterance_id}] {c.speech_act:10s} target={c.target_resource}")
        print(f"      {c.claim}")
    print()

    print("--- Pass 2: cues scoped per claim ---")
    for c in claims:
        c.cues = pass2_cues(client, c)

    print("\n=== combined ===\n")
    for c in claims:
        cue_str = ", ".join(f"{x.type}:{x.token!r}" for x in c.cues) or "(none)"
        print(f"[{c.utterance_id}] {c.speech_act}  target={c.target_resource}")
        print(f"    claim : {c.claim}")
        print(f"    cues  : {cue_str}\n")

    print("--- success check ---")
    print("The claim that will resolve to CONTRADICT (adherence / QD-vs-BID) should now")
    print("carry the booster ('always'). If confidence still sits only on a TRUE claim,")
    print("Pass 1 paraphrase is still too literal -> that's the next thing to tighten.")
