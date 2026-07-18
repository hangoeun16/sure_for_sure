"""
gen_followups.py — generate follow-up transcripts that EXPRESS the authored
states, without naming the target labels in the dialogue.

Rigor: the model is given a natural-language SCENARIO (what happens in the
visit), NOT the state labels (commitment=emphatic, resolution=resolved...).
If the labels leaked into the prompt, extraction later would be a readback,
not a test. The generated transcript must let a human — and the extractor —
INFER the state from ordinary clinical talk.

Run:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 gen_followups.py
Writes: followups/{A-V2,A-V3,B-V2,C-V2}.txt
"""

import os, sys

# scenarios describe WHAT HAPPENS, in clinical prose — never the state enums.
SCENARIOS = {
    "A-V2": (
        "Follow-up for an asthma patient ~6 weeks after a visit where they had quietly "
        "cut their twice-daily controller inhaler down to once a day (mornings). Since "
        "then they've started waking with some nighttime chest tightness and are reaching "
        "for their rescue inhaler more often. The patient still feels the once-daily "
        "controller is fine and puts the worsening down to the weather / seasonal change. "
        "They are still only using it once a day. The clinician takes the history but the "
        "issue isn't settled by end of visit."
    ),
    "A-V3": (
        "Later follow-up for the same patient. They have now stopped the controller "
        "inhaler entirely, saying it wasn't really doing anything for them. They're using "
        "the rescue inhaler frequently and getting winded on stairs / limiting activity. "
        "They're matter-of-fact about having stopped. The clinician takes the history; it "
        "isn't resolved in this visit."
    ),
    "B-V2": (
        "Follow-up where the clinician explicitly clarifies that once-daily was NOT the "
        "intended regimen, reviews the patient's symptoms and inhaler technique, and they "
        "agree together to restart the twice-daily controller. The clinician states the "
        "plan and the patient repeats it back and agrees. The matter is settled in this visit."
    ),
    "C-V2": (
        "Follow-up where the patient reports taking the controller once daily and says a "
        "lung specialist approved this reduction at a recent appointment. In the room, the "
        "active medication list still shows twice daily, but there is a more recent "
        "pulmonology note approving the once-daily step-down. Nothing is wrong with the "
        "patient's account; the records simply disagree with each other by date."
    ),
}

SYSTEM = """You write short, realistic primary-care follow-up transcripts in the SAME
style as a clinical OSCE transcript: line-tagged, alternating clinician and patient,
natural disfluencies, no narration. Use tags like [D-1], [P-1], [D-2], [P-2]...

Rules:
- Render ONLY what is said in the room. Do NOT label emotions, certainty, or intent.
- Let the patient's confidence, actions, and reasoning show through ordinary speech,
  not through clinical meta-terms (the patient never says things like "I'm emphatic"
  or "my adherence is partial").
- Keep it short: 10-16 exchanges. Focus on the medication/regimen thread; minimal
  small talk.
- Do not resolve anything the scenario says is unresolved; do resolve what it says
  is settled.
Return ONLY the transcript text."""


def generate(tag, scenario, client, model="claude-sonnet-4-6"):
    msg = client.messages.create(
        model=model, max_tokens=1500, system=SYSTEM,
        messages=[{"role": "user",
                   "content": f"Scenario ({tag}):\n{scenario}\n\nWrite the transcript."}],
    )
    return msg.content[0].text.strip()


if __name__ == "__main__":
    try:
        import anthropic
    except ImportError:
        sys.exit("pip install anthropic")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("export ANTHROPIC_API_KEY=sk-ant-... first")

    client = anthropic.Anthropic()
    os.makedirs("followups", exist_ok=True)
    for tag, scenario in SCENARIOS.items():
        print(f"generating {tag} ...")
        txt = generate(tag, scenario, client)
        path = f"followups/{tag}.txt"
        with open(path, "w") as f:
            f.write(txt)
        print(f"  -> {path}  ({len(txt.split())} words)")
    print("\nDone. Read them and sanity-check: does the state show WITHOUT being named?")
    print("Next (tomorrow): run the extractor on these and check it recovers the")
    print("authored states in fixtures_abc.py — that's step 5, the real test.")
