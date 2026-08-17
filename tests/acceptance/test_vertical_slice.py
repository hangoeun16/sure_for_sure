from __future__ import annotations

from pipeline.models import ActionRoute, EvidenceRelation


def _assert_exact_spans(transcript: str, claim) -> None:
    assert claim.supporting_spans
    for span in claim.supporting_spans:
        assert transcript[span.start_char : span.end_char] == span.text


def test_case_a_direct_active_claim(analyze_case) -> None:
    record, analysis = analyze_case("case_a")
    claim = analysis.claims[0]
    assert claim.medication_name == "metoprolol"
    assert claim.dose_value == 100
    assert claim.dose_unit == "mg"
    assert claim.frequency == "every morning"
    assert claim.status == "active"
    _assert_exact_spans(record["transcript"], claim)


def test_case_b_discontinuation_is_never_active(analyze_case) -> None:
    record, analysis = analyze_case("case_b")
    claim = analysis.claims[0]
    assert claim.status in {"stopped", "discontinued"}
    assert claim.status != "active"
    assert claim.negated is True
    assert claim.negation_span is not None
    _assert_exact_spans(record["transcript"], claim)


def test_case_c_contextual_short_answer_cites_both_turns(analyze_case) -> None:
    record, analysis = analyze_case("case_c")
    claim = analysis.claims[0]
    assert claim.medication_name == "lisinopril"
    assert claim.frequency == "daily"
    assert claim.status == "active"
    assert {analysis.turns[span.turn_index].speaker.value for span in claim.supporting_spans} == {
        "DR",
        "PT",
    }
    _assert_exact_spans(record["transcript"], claim)


def test_case_d_uncertainty_is_explicit_and_not_high_confidence(analyze_case) -> None:
    record, analysis = analyze_case("case_d")
    claim = analysis.claims[0]
    assert claim.medication_name == "atenolol"
    assert claim.dose_value == 50
    assert claim.dose_unit == "mg"
    assert claim.confidence.cues
    assert claim.confidence.level.value in {"hedged", "unclear"}
    _assert_exact_spans(record["transcript"], claim)


def test_case_e_adherence_gap_is_clarification_worthy(analyze_case) -> None:
    record, analysis = analyze_case("case_e")
    claim = analysis.claims[0]
    assert claim.status == "active"
    assert claim.adherence_gap is True
    assert claim.adherence_span is not None
    assert "miss" in claim.adherence_span.text.lower()
    assert any(
        action.route == ActionRoute.PATIENT_CLARIFICATION and action.claim_id == claim.claim_id
        for action in analysis.actions
    )
    _assert_exact_spans(record["transcript"], claim)


def test_case_f_later_resolution_suppresses_repeat_question(analyze_case) -> None:
    _, analysis = analyze_case("case_f")
    earlier = analysis.claims[0]
    resolution = analysis.resolutions[earlier.claim_id]
    assert resolution.resolved is True
    assert resolution.resolved_fields == ["dose_value"]
    assert not any(
        action.route == ActionRoute.PATIENT_CLARIFICATION and action.claim_id == earlier.claim_id
        for action in analysis.actions
    )
    assert any(action.route == ActionRoute.CHART_CLEANUP for action in analysis.actions)


def test_case_g_unseen_medication_links_dynamically(analyze_case) -> None:
    _, analysis = analyze_case("case_g")
    claim = analysis.claims[0]
    links = analysis.links[claim.claim_id]
    assert claim.medication_name == "rivaroxaban"
    assert [link.evidence_id for link in links] == ["med-g-unseen"]
    assert analysis.divergences[claim.claim_id].relation == EvidenceRelation.SUPPORT


def test_case_h_no_claim_means_no_action(analyze_case) -> None:
    _, analysis = analyze_case("case_h")
    assert analysis.claims == []
    assert analysis.divergences == {}
    assert analysis.actions == []


def test_case_i_multiple_medications_are_not_merged(analyze_case) -> None:
    record, analysis = analyze_case("case_i")
    assert [claim.medication_name for claim in analysis.claims] == ["losartan", "amlodipine"]
    assert [claim.status for claim in analysis.claims] == ["active", "stopped"]
    first, second = analysis.claims
    assert first.supporting_spans[0].text != second.supporting_spans[0].text
    assert first.supporting_spans[0].end_char <= second.supporting_spans[0].start_char
    _assert_exact_spans(record["transcript"], first)
    _assert_exact_spans(record["transcript"], second)


def test_case_j_resolution_changes_routing(analyze_case) -> None:
    _, unresolved = analyze_case("case_j_unresolved")
    _, resolved = analyze_case("case_j_resolved")
    unresolved_routes = {action.route for action in unresolved.actions}
    resolved_routes = {action.route for action in resolved.actions}
    assert ActionRoute.PATIENT_CLARIFICATION in unresolved_routes
    assert ActionRoute.PATIENT_CLARIFICATION not in resolved_routes
    unresolved_claim = unresolved.claims[0]
    resolved_claim = resolved.claims[0]
    assert unresolved.resolutions[unresolved_claim.claim_id].resolved is False
    assert resolved.resolutions[resolved_claim.claim_id].resolved is True
    assert unresolved_routes != resolved_routes


def test_complete_provenance_is_present(analyze_case) -> None:
    _, analysis = analyze_case("case_a")
    assert analysis.source is not None
    assert analysis.source.source_record_id == "case_a"
    assert analysis.source.source_record_index >= 0
    assert len(analysis.source.source_sha256) == 64
    assert len(analysis.source.record_sha256) == 64
    claim = analysis.claims[0]
    assert claim.extractor.provider
    assert claim.extractor.model
    evidence = analysis.record_evidence[0]
    assert evidence.resource_id == "med-a"
    assert evidence.source_path
    assert analysis.links[claim.claim_id][0].rationale
    assert analysis.divergences[claim.claim_id].rationale
