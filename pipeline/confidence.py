"""Deterministic patient-commitment semantics for extracted medication claims."""

from __future__ import annotations

import re
from collections.abc import Iterable

from pipeline.models import ConfidenceCueType, ConfidenceLevel

_BOOSTER_PATTERNS = (
    re.compile(r"\balways\b"),
    re.compile(r"\bnever\b"),
    re.compile(r"\bdefinitely\b"),
    re.compile(r"\bfor sure\b"),
    re.compile(r"\bi know\b"),
    re.compile(r"\b100\s*%"),
    re.compile(r"\bno problems at all\b"),
)

_HEDGE_PATTERNS = (
    re.compile(r"\bmaybe\b"),
    re.compile(r"\bi think\b"),
    re.compile(r"\bi guess\b"),
    re.compile(r"\bnot sure\b"),
    re.compile(r"\bcould be\b"),
    re.compile(r"\bprobably\b"),
    re.compile(r"\bi (?:do not|don't) know\b"),
    re.compile(r"\bi(?:'m| am) uncertain\b"),
    re.compile(r"\b(?:could not|couldn't) tell\b"),
    re.compile(r"\bif i take\b"),
)


def derive_confidence_level(cue_types: Iterable[ConfidenceCueType]) -> ConfidenceLevel:
    """Derive linguistic commitment without consulting claim completeness or the chart."""
    types = set(cue_types)
    has_hedge = ConfidenceCueType.HEDGE in types
    has_booster = ConfidenceCueType.BOOSTER in types
    if has_hedge and has_booster:
        return ConfidenceLevel.NEUTRAL
    if has_hedge:
        return ConfidenceLevel.HEDGED
    if has_booster:
        return ConfidenceLevel.EMPHATIC
    return ConfidenceLevel.NEUTRAL


def cue_rationale(cue_types: Iterable[ConfidenceCueType]) -> str:
    types = set(cue_types)
    has_hedge = ConfidenceCueType.HEDGE in types
    has_booster = ConfidenceCueType.BOOSTER in types
    if has_hedge and has_booster:
        return "Explicit hedge and booster cues conflict, so commitment is neutral."
    if has_hedge:
        return "An explicit patient hedge lowers linguistic commitment."
    if has_booster:
        return "An explicit patient booster strengthens linguistic commitment."
    if ConfidenceCueType.HESITATION in types:
        return "Hesitation is preserved, but without a hedge the assertion remains neutral."
    if types & {ConfidenceCueType.SELF_JUSTIFICATION, ConfidenceCueType.AUTHORITY}:
        return "Evidential cues are preserved but do not independently change confidence."
    return "No explicit hedge or booster; this is an ordinary neutral assertion."


def lexical_cue_matches_type(cue_type: ConfidenceCueType, quote: str) -> bool:
    """Enforce the documented lexical boundary for model-returned certainty cues."""
    normalized = " ".join(
        quote.lower().replace("’", "'").replace("‘", "'").split()
    )
    if cue_type == ConfidenceCueType.BOOSTER:
        return any(pattern.search(normalized) for pattern in _BOOSTER_PATTERNS)
    if cue_type == ConfidenceCueType.HEDGE:
        return any(pattern.search(normalized) for pattern in _HEDGE_PATTERNS)
    if cue_type == ConfidenceCueType.HESITATION:
        return normalized in {"...", "…"}
    return True
