"""Deterministic normalization shared by claim and record processing."""

from __future__ import annotations

import re

_FORMULATION_WORDS = {
    "actuat",
    "auto",
    "injectable",
    "injector",
    "tablet",
    "tablets",
    "capsule",
    "capsules",
    "oral",
    "solution",
    "injection",
    "extended",
    "release",
    "delayed",
    "chewable",
    "cream",
    "gel",
    "mucosal",
    "spray",
    "topical",
    "mg",
    "mcg",
    "g",
    "ml",
    "hr",
}


def _text(value: object | None) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).strip().lower().split())
    return result or None


def normalize_medication_name(value: object | None) -> str:
    text = _text(value) or ""
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml)\b", " ", text)
    text = re.sub(r"[^a-z0-9 -]", " ", text)
    tokens = [token for token in text.replace("-", " ").split() if token not in _FORMULATION_WORDS]
    return " ".join(tokens)


def medication_name_tokens(value: object | None) -> set[str]:
    return {token for token in normalize_medication_name(value).split() if len(token) > 1}


def medication_names_compatible(left: object | None, right: object | None) -> bool:
    """Match a spoken generic name to a compatible RxNorm-style formulation."""
    left_name = normalize_medication_name(left)
    right_name = normalize_medication_name(right)
    if not left_name or not right_name:
        return False
    if left_name == right_name:
        return True
    left_tokens = medication_name_tokens(left_name)
    right_tokens = medication_name_tokens(right_name)
    denominator = min(len(left_tokens), len(right_tokens))
    return bool(denominator and len(left_tokens & right_tokens) / denominator >= 0.6)


def normalize_dose_unit(value: object | None) -> str | None:
    text = _text(value)
    if not text:
        return None
    compact = text.replace(".", "")
    aliases = {
        "milligram": "mg",
        "milligrams": "mg",
        "mg": "mg",
        "microgram": "mcg",
        "micrograms": "mcg",
        "mcg": "mcg",
        "µg": "mcg",
        "gram": "g",
        "grams": "g",
        "g": "g",
        "milliliter": "ml",
        "milliliters": "ml",
        "ml": "ml",
    }
    return aliases.get(compact, compact)


def normalize_frequency(value: object | None) -> str | None:
    text = _text(value)
    if not text:
        return None
    replacements = {
        "once daily": "daily",
        "every day": "daily",
        "once a day": "daily",
        "qd": "daily",
        "each morning": "every morning",
        "in the morning": "every morning",
        "qam": "every morning",
        "twice daily": "twice daily",
        "twice a day": "twice daily",
        "bid": "twice daily",
        "three times daily": "three times daily",
        "tid": "three times daily",
    }
    return replacements.get(text, text)


def normalize_route(value: object | None) -> str | None:
    text = _text(value)
    if not text:
        return None
    if "oral" in text or "mouth" in text:
        return "oral"
    if "intraven" in text or text == "iv":
        return "intravenous"
    if "subcut" in text:
        return "subcutaneous"
    return text.removesuffix(" route")


def normalize_status(value: object | None) -> str | None:
    text = _text(value)
    if not text:
        return None
    aliases = {
        "current": "active",
        "taking": "active",
        "ceased": "stopped",
        "inactive": "stopped",
        "completed": "stopped",
    }
    return aliases.get(text, text)
