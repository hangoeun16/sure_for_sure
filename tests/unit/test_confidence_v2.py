from __future__ import annotations

import pytest
from pipeline.confidence import derive_confidence_level
from pipeline.input_contract import EncounterInput
from pipeline.models import ConfidenceCueType, ConfidenceCueWarningCode, ConfidenceLevel
from pipeline.providers import StubClaimExtractionProvider
from pipeline.runner import run_pipeline


def _claim(
    patient_text: str,
    *,
    medication_name: str = "metoprolol",
    cues: list[dict] | None = None,
    prefix: str = "",
):
    transcript = f"{prefix}PT: {patient_text}"
    patient_turn_index = len(prefix.rstrip("\n").splitlines()) if prefix else 0
    encounter = EncounterInput(
        id="confidence-v2-test",
        metadata={},
        patient_context={},
        encounter_fhir={},
        transcript=transcript,
        note="",
        after_visit_summary="",
        after_visit_summary_provenance={},
    )
    output = {
        "claims": [
            {
                "medication_name": medication_name,
                "confidence_cues": cues or [],
                "supporting_quotes": [
                    {"turn_index": patient_turn_index, "quote": patient_text}
                ],
            }
        ]
    }
    return run_pipeline(encounter, StubClaimExtractionProvider(output)).claims[0]


@pytest.mark.parametrize(
    ("cue_types", "expected"),
    [
        ([], ConfidenceLevel.NEUTRAL),
        ([ConfidenceCueType.HESITATION], ConfidenceLevel.NEUTRAL),
        ([ConfidenceCueType.SELF_JUSTIFICATION], ConfidenceLevel.NEUTRAL),
        ([ConfidenceCueType.AUTHORITY], ConfidenceLevel.NEUTRAL),
        ([ConfidenceCueType.HEDGE], ConfidenceLevel.HEDGED),
        ([ConfidenceCueType.BOOSTER], ConfidenceLevel.EMPHATIC),
        (
            [ConfidenceCueType.HEDGE, ConfidenceCueType.BOOSTER],
            ConfidenceLevel.NEUTRAL,
        ),
    ],
)
def test_resolution_table_is_deterministic(cue_types, expected) -> None:
    assert derive_confidence_level(cue_types) == expected


@pytest.mark.parametrize(
    "patient_text",
    [
        "I take metoprolol.",
        "I take metoprolol 50 mg every morning.",
        "I take the little pill.",
        "I still take metoprolol every day.",
        "I have taken it daily for a couple of years.",
        "I really take a little metoprolol.",
        "I take kind of a small dose of metoprolol.",
    ],
)
def test_ordinary_or_incomplete_assertions_remain_neutral(patient_text: str) -> None:
    claim = _claim(patient_text)
    assert claim.confidence.level == ConfidenceLevel.NEUTRAL
    assert claim.confidence.score == 0.67
    assert claim.confidence.cues == []


def test_explicit_hedge_is_grounded_and_hedged() -> None:
    patient_text = "I think I take metoprolol."
    claim = _claim(
        patient_text,
        cues=[{"type": "hedge", "turn_index": 0, "quote": "I think"}],
    )
    assert claim.confidence.level == ConfidenceLevel.HEDGED
    assert claim.confidence.score == 0.33
    cue = claim.confidence.cues[0]
    assert cue.type == ConfidenceCueType.HEDGE
    assert patient_text[cue.span.start_char - 4 : cue.span.end_char - 4] == "I think"


def test_missing_medication_identity_and_dose_are_still_neutral() -> None:
    claim = _claim(
        "I take something when my migraine gets bad.",
        medication_name="unspecified migraine medication",
    )
    assert claim.dose_value is None
    assert claim.confidence.level == ConfidenceLevel.NEUTRAL


def test_explicit_booster_is_grounded_and_emphatic() -> None:
    claim = _claim(
        "I definitely take metoprolol.",
        cues=[{"type": "booster", "turn_index": 0, "quote": "definitely"}],
    )
    assert claim.confidence.level == ConfidenceLevel.EMPHATIC
    assert claim.confidence.score == 1.0


@pytest.mark.parametrize("ellipsis", ["...", "…"])
def test_ellipsis_is_detected_as_neutral_hesitation(ellipsis: str) -> None:
    claim = _claim(f"I take {ellipsis} metoprolol.")
    assert claim.confidence.level == ConfidenceLevel.NEUTRAL
    assert [(cue.type, cue.span.text) for cue in claim.confidence.cues] == [
        (ConfidenceCueType.HESITATION, ellipsis)
    ]


def test_hesitation_does_not_override_hedge_or_booster() -> None:
    hedged = _claim(
        "I think... I take metoprolol.",
        cues=[{"type": "hedge", "turn_index": 0, "quote": "I think"}],
    )
    emphatic = _claim(
        "I definitely... take metoprolol.",
        cues=[{"type": "booster", "turn_index": 0, "quote": "definitely"}],
    )
    assert hedged.confidence.level == ConfidenceLevel.HEDGED
    assert {cue.type for cue in hedged.confidence.cues} == {
        ConfidenceCueType.HEDGE,
        ConfidenceCueType.HESITATION,
    }
    assert emphatic.confidence.level == ConfidenceLevel.EMPHATIC
    assert {cue.type for cue in emphatic.confidence.cues} == {
        ConfidenceCueType.BOOSTER,
        ConfidenceCueType.HESITATION,
    }


def test_booster_and_hedge_resolve_to_neutral() -> None:
    claim = _claim(
        "I think I definitely take metoprolol.",
        cues=[
            {"type": "hedge", "turn_index": 0, "quote": "I think"},
            {"type": "booster", "turn_index": 0, "quote": "definitely"},
        ],
    )
    assert claim.confidence.level == ConfidenceLevel.NEUTRAL


def test_self_justification_is_grounded_but_remains_neutral() -> None:
    claim = _claim(
        "I stopped metoprolol because it made me dizzy.",
        cues=[
            {
                "type": "self_justification",
                "turn_index": 0,
                "quote": "because it made me dizzy",
            }
        ],
    )
    assert claim.confidence.level == ConfidenceLevel.NEUTRAL
    assert claim.confidence.cues[0].type == ConfidenceCueType.SELF_JUSTIFICATION


def test_observed_out_of_span_booster_is_warned_and_claim_remains_valid() -> None:
    claim = _claim(
        "I take metoprolol.",
        prefix="PT: She never misses.\n",
        cues=[{"type": "booster", "turn_index": 0, "quote": "She never misses."}],
    )
    assert claim.confidence.level == ConfidenceLevel.NEUTRAL
    assert claim.confidence.cues == []
    assert len(claim.confidence.validation_warnings) == 1
    warning = claim.confidence.validation_warnings[0]
    assert warning.code == ConfidenceCueWarningCode.OUTSIDE_PATIENT_SUPPORT
    assert warning.quote == "She never misses."


def test_observed_misclassified_booster_is_warned_and_claim_remains_valid() -> None:
    quote = (
        "I do notice when I skip — I get foggy and my legs feel like sandbags."
    )
    claim = _claim(
        quote,
        cues=[{"type": "booster", "turn_index": 0, "quote": quote}],
    )
    assert claim.confidence.level == ConfidenceLevel.NEUTRAL
    assert claim.confidence.cues == []
    assert len(claim.confidence.validation_warnings) == 1
    warning = claim.confidence.validation_warnings[0]
    assert warning.code == ConfidenceCueWarningCode.TYPE_MISMATCH
    assert warning.quote == quote


def test_invalid_cue_is_discarded_without_masking_a_valid_hedge() -> None:
    patient_text = "I think I take metoprolol every day."
    claim = _claim(
        patient_text,
        cues=[
            {"type": "booster", "turn_index": 0, "quote": "every day"},
            {"type": "hedge", "turn_index": 0, "quote": "I think"},
        ],
    )
    assert claim.confidence.level == ConfidenceLevel.HEDGED
    assert [cue.type for cue in claim.confidence.cues] == [ConfidenceCueType.HEDGE]
    assert [warning.code for warning in claim.confidence.validation_warnings] == [
        ConfidenceCueWarningCode.TYPE_MISMATCH
    ]


def test_ellipsis_is_detected_only_in_patient_supporting_spans() -> None:
    claim = _claim(
        "I take metoprolol.",
        prefix="DR: You paused... are you certain?\n",
    )
    assert claim.confidence.cues == []


def test_bracketed_ellipsis_is_not_a_hesitation() -> None:
    claim = _claim("I take [ ... ] metoprolol.")
    assert claim.confidence.cues == []
