"""Stage 01: parse labeled dialogue without clinical inference."""

from __future__ import annotations

import re

from pipeline.models import DialogueTurn, Speaker, TranscriptSpan
from pipeline.state import PipelineState

TURN_RE = re.compile(r"(?m)^(?P<label>[A-Za-z][A-Za-z0-9_-]*):[ \t]*(?P<text>[^\r\n]*)")


def _speaker(label: str) -> Speaker:
    upper = label.upper()
    if upper in {"PT", "PATIENT"}:
        return Speaker.PATIENT
    if upper in {"DR", "DOCTOR", "CLINICIAN", "MD"}:
        return Speaker.CLINICIAN
    if upper in {"RN", "NURSE"}:
        return Speaker.NURSE
    if upper in {"FAMILY", "CAREGIVER"}:
        return Speaker.FAMILY
    return Speaker.OTHER


def run(state: PipelineState) -> PipelineState:
    state.turns = [
        DialogueTurn(
            index=index,
            speaker=_speaker(match.group("label")),
            speaker_label=match.group("label").upper(),
            text=match.group("text"),
            start_char=match.start("text"),
            end_char=match.end("text"),
        )
        for index, match in enumerate(TURN_RE.finditer(state.encounter.transcript))
    ]
    return state


def exact_span(state: PipelineState, *, turn_index: int, quote: str) -> TranscriptSpan:
    if not quote:
        raise ValueError("Exact quote cannot be empty.")
    try:
        turn = state.turns[turn_index]
    except IndexError as exc:
        raise ValueError(f"Unknown turn index {turn_index}.") from exc
    offset = turn.text.find(quote)
    if offset < 0:
        raise ValueError(f"Quote is not an exact substring of turn {turn_index}: {quote!r}")
    start = turn.start_char + offset
    end = start + len(quote)
    if state.encounter.transcript[start:end] != quote:
        raise ValueError("Exact quote offsets did not round-trip.")
    return TranscriptSpan(turn_index=turn_index, start_char=start, end_char=end, text=quote)
