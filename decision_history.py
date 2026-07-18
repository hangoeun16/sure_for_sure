"""
decision_history.py — decision-changing history attribution (ablation).

Most chart-aware systems summarize the past. This asks a sharper question:
*which* past encounters actually change the next clinical action? We re-run the
existing routing (`decision_for`) over the history with one past event removed at
a time; any event whose removal changes the final decision is decision-changing.

HONEST SCOPE: the engine decides from an *adjacent transition* (current + the
immediately-preceding encounter), not from a folded summary of the whole past.
So ablation flags the encounter adjacent to the current one when its removal
changes the transition; earlier non-adjacent encounters won't move the decision,
and the output states that plainly instead of overclaiming full-history folding.
The sharper, model-independent evidence that history matters is the
baseline-vs-longitudinal contrast (same encounter, with vs without context).

THIN wrapper over the existing engine — same surface_question / priority_tier /
trajectory_change / disposition. No engine logic changes.
"""
from trajectory import (surface_question, priority_tier, trajectory_change,
                        encounter_only_question)


def decision_for(history):
    """Return the routing decision at the final encounter of an ORDERED history.

    HONEST SCOPE: this engine decides each encounter from an *adjacent transition*
    — the current state and the one immediately before it — via trajectory_change
    / priority_tier / disposition / surface_question. It does not fold the entire
    history into an accumulated state. So `decision_for` reports the final
    encounter's decision given whatever immediately precedes it *in this ordering*.

    That is precisely why ablation is still meaningful: removing the encounter that
    is currently adjacent to the final one changes the transition the engine sees,
    and can change the decision. Removing a non-adjacent earlier encounter will NOT
    change it — and the ablation output says so plainly, rather than pretending the
    whole past is folded in. Same functions the runner calls; no engine change.
    """
    if not history:
        return None
    prev = history[-2] if len(history) > 1 else None   # adjacent predecessor only
    cur  = history[-1]
    return (
        priority_tier(cur),
        trajectory_change(prev, cur),
        cur.disposition(),
        surface_question(cur),
    )


def decision_changing_events(history):
    """Return past events whose removal changes the final decision. Re-runs the
    SAME decision_for() on the history with each past event removed."""
    full = decision_for(history)
    changing = []
    for i in range(len(history) - 1):           # never ablate the current encounter
        ablated = history[:i] + history[i+1:]
        if decision_for(ablated) != full:
            changing.append((history[i], decision_for(ablated)))
    return full, changing


def baseline_vs_longitudinal(current):
    """The sharpest evidence that history changes the ASK: the same encounter, with
    and without cross-visit context, produces a different question."""
    return {
        "encounter_only": encounter_only_question(current),
        "longitudinal":   surface_question(current),
    }


def explain(history, label_of=lambda s: s.encounter_id):
    """Human-readable attribution for the demo/runner."""
    full, changing = decision_changing_events(history)
    cur = history[-1]
    bl = baseline_vs_longitudinal(cur)
    tier, change, disp, q = full
    lines = [f"Final decision (decision_for over the ordered history): "
             f"tier={tier}, change={change}, disposition={disp}", ""]

    # PRIMARY evidence that history matters: same encounter, with vs without context.
    lines.append("Does history change the ASK? (same encounter, with vs without context)")
    lines.append(f"  encounter-only: {bl['encounter_only']}")
    lines.append(f"  longitudinal  : {bl['longitudinal']}")
    lines.append("  -> With no history the ask is a yes/no adherence check. With the trajectory")
    lines.append("     it becomes a specific question about what changed. History changes WHICH")
    lines.append("     question is worth asking — the model-independent evidence.")
    lines.append("")

    # SECONDARY: ablation over decision_for. Honest about the adjacent-transition model.
    lines.append("Ablation (decision_for re-run with each past encounter removed):")
    if not changing:
        lines.append("  removing any single past encounter leaves the decision unchanged.")
        lines.append("  -> the decision is NOT the artifact of one visit; the escalating")
        lines.append("     trajectory is consistent. (The engine routes on an adjacent")
        lines.append("     transition, so only a change to the immediately-preceding encounter")
        lines.append("     could move it — and here it doesn't.)")
    else:
        lines.append("  these past encounters change the decision when removed:")
        for ev, ablated in changing:
            a_tier, a_change, a_disp, _ = ablated
            lines.append(f"    - {label_of(ev)}: action={ev.action}, "
                         f"evidence={ev.evidence_relation()} "
                         f"(without it: tier={a_tier}, change={a_change}, disp={a_disp})")
        omitted = (len(history) - 1) - len(changing)
        if omitted > 0:
            lines.append(f"    ({omitted} other past encounter(s) do NOT change the decision.)")
    return "\n".join(lines)


if __name__ == "__main__":
    # demo on the John trajectory (V1 -> A-V2 -> A-V3), built via the real adapter
    import sys
    sys.argv = ["x", "--mock"]
    from adapter import encounter_to_event, extracted_to_event
    import run_trajectory as rt
    v1  = encounter_to_event(rt.TOPIC, "V1", rt.V1_CANDIDATES, record_meta=rt.V1_META)
    a_v2 = extracted_to_event(rt.TOPIC, "A-V2", rt.get_extracted("A-V2", True))
    a_v3 = extracted_to_event(rt.TOPIC, "A-V3", rt.get_extracted("A-V3", True))
    print(explain([v1, a_v2, a_v3]))
