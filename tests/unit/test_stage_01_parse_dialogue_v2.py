from pipeline.input_contract import EncounterInput
from pipeline.stage_01_parse_dialogue import exact_span, run
from pipeline.state import PipelineState


def test_turn_and_quote_offsets_round_trip() -> None:
    transcript = "DR: Which dose?\nPT: I take 20 mg every morning."
    encounter = EncounterInput(
        id="span-test",
        metadata={},
        patient_context={},
        encounter_fhir={},
        transcript=transcript,
        note="",
        after_visit_summary="",
        after_visit_summary_provenance={},
    )
    state = run(PipelineState(encounter=encounter))
    span = exact_span(state, turn_index=1, quote="20 mg every morning")
    assert transcript[span.start_char : span.end_char] == span.text
