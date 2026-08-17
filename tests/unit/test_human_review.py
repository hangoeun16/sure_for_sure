from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from backend.human_review import (
    ClaimReviewPatch,
    HumanReviewService,
    MissedClaimReviewPatch,
    ProgressPatch,
    ReviewError,
    _assert_unique_reference_linkage,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _frozen_run(tmp_path: Path) -> tuple[str, Path, Path]:
    run_id = "frozen-review-test"
    runs_root = tmp_path / "runs"
    run = runs_root / run_id
    run.mkdir(parents=True)
    _write_json(
        run / "manifest.json",
        {
            "run_id": run_id,
            "run_kind": "batch",
            "model": "claude-test",
            "prompt_version": "medication_claim_extraction_v2",
            "prompt_hash": "prompt-hash",
            "dataset_file": "organizer.jsonl",
            "dataset_sha256": "dataset-hash",
        },
    )
    turns = [
        {
            "index": 0,
            "speaker": "DR",
            "speaker_label": "DR",
            "text": "Do you take your medicine?",
            "start_char": 4,
            "end_char": 30,
        },
        {
            "index": 1,
            "speaker": "PT",
            "speaker_label": "PT",
            "text": "I take metoprolol 50 mg daily.",
            "start_char": 35,
            "end_char": 68,
        },
        {
            "index": 2,
            "speaker": "PT",
            "speaker_label": "PT",
            "text": "I stopped aspirin yesterday.",
            "start_char": 73,
            "end_char": 101,
        },
    ]
    claim = {
        "claim_id": "claim-1",
        "medication_name": "metoprolol",
        "status": "active",
        "dose_value": 50,
        "dose_unit": "mg",
        "frequency": "daily",
        "route": None,
        "negated": False,
        "negation_span": None,
        "adherence_gap": False,
        "adherence_span": None,
        "supporting_spans": [
            {
                "turn_index": 1,
                "start_char": 35,
                "end_char": 68,
                "text": "I take metoprolol 50 mg daily.",
            }
        ],
        "confidence": {
            "level": "neutral",
            "score": 0.67,
            "cues": [],
            "validation_warnings": [],
            "rationale": "ordinary assertion",
        },
        "first_turn": 1,
        "last_turn": 1,
        "extractor": {
            "provider": "anthropic",
            "model": "claude-test",
            "request_id": "message-test",
            "schema_version": "claim-extraction-v2",
            "attempts": 1,
            "usage": {},
        },
    }
    downstream = {
        "record_id": "record-1",
        "record_index": 0,
        "pipeline_output": {
            "encounter_id": "record-1",
            "turns": turns,
            "claims": [claim],
            "record_evidence": [
                {"medication_name": "aspirin", "evidence_id": "rx-1"}
            ],
        },
    }
    (run / "downstream_results.jsonl").write_text(
        json.dumps(downstream) + "\n", encoding="utf-8"
    )
    for name in (
        "raw_outputs.jsonl",
        "validated_claims.jsonl",
        "records.jsonl",
        "failures.jsonl",
    ):
        (run / name).write_text(f"frozen-{name}\n", encoding="utf-8")
    _write_json(run / "summary.json", {"total_extracted_claims": 1})
    return run_id, runs_root, tmp_path / "human-review"


def _service(tmp_path: Path) -> HumanReviewService:
    run_id, runs_root, review_root = _frozen_run(tmp_path)
    return HumanReviewService(
        run_id=run_id,
        runs_root=runs_root,
        review_root=review_root,
    )


def _complete_claim_patch(**overrides) -> ClaimReviewPatch:
    values = {
        "claim_assessment": "correct_claim",
        "supporting_quote": "correct",
        "field_reviews": {
            "medication_identity": "correct",
            "dose_value": "incorrect",
            "dose_unit": "not_stated_by_patient",
            "frequency": "ambiguous",
            "route": "needs_domain_review",
            "status_adherence": "correct",
            "negation": "not_stated_by_patient",
        },
        "confidence_cues": "no_cue_should_be_present",
        "derived_confidence": "correct_by_rubric",
        "hallucination": "no",
    }
    values.update(overrides)
    return ClaimReviewPatch.model_validate(values)


def _hashes(path: Path) -> dict[str, str]:
    return {
        item.name: hashlib.sha256(item.read_bytes()).hexdigest()
        for item in path.iterdir()
        if item.is_file()
    }


def test_autosave_resume_and_ids_remain_tied_to_source(tmp_path: Path) -> None:
    service = _service(tmp_path)
    source_hashes = _hashes(service.dataset.run_directory)
    bootstrap = service.bootstrap()
    saved = service.save_claim_review(
        "claim-1", ClaimReviewPatch(claim_assessment="ambiguous")
    )
    service.save_progress(ProgressPatch(queue="predictions", item_id="claim-1"))

    resumed = HumanReviewService(
        run_id=service.run_id,
        runs_root=service.dataset.run_directory.parent,
        review_root=service.workspace.parent,
    )
    queue = resumed.prediction_queue()
    assert bootstrap["prediction_count"] == 1
    assert saved["record_id"] == "record-1"
    assert queue[0]["review"]["claim_id"] == "claim-1"
    assert resumed.progress()["last_item_id"] == "claim-1"
    with pytest.raises(ReviewError, match="Unknown claim ID"):
        service.save_claim_review(
            "invented-claim", ClaimReviewPatch(claim_assessment="correct_claim")
        )
    assert _hashes(service.dataset.run_directory) == source_hashes


def test_recall_candidates_use_uncovered_patient_speech_only(tmp_path: Path) -> None:
    service = _service(tmp_path)
    candidates = service.dataset.missed_candidates
    assert len(candidates) == 1
    assert candidates[0]["turn"]["speaker"] == "PT"
    assert candidates[0]["turn"]["text"] == "I stopped aspirin yesterday."
    assert "claims" not in candidates[0]
    assert "stopped" in candidates[0]["signals"]


def test_reference_claims_come_only_from_explicit_human_decisions(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    service.bootstrap()
    service.save_claim_review("claim-1", _complete_claim_patch())
    candidate = service.dataset.missed_candidates[0]
    service.save_missed_review(
        candidate["candidate_id"],
        MissedClaimReviewPatch(
            decision="likely_missed_medication_claim",
            supporting_quote="stopped aspirin",
            medication_name_as_spoken="aspirin",
            status_adherence_as_spoken="stopped",
        ),
    )
    finalized = service.finalize()
    references = [
        json.loads(line)
        for line in service.reference_path.read_text(encoding="utf-8").splitlines()
    ]
    assert finalized["reference_claims"] == 2
    assert {item["reference_source"] for item in references} == {
        "confirmed_prediction",
        "human_identified_missed_claim",
    }
    missed_reference = next(
        item
        for item in references
        if item["reference_source"] == "human_identified_missed_claim"
    )
    assert missed_reference["supporting_spans"][0]["text"] == "stopped aspirin"


def test_ambiguous_and_domain_review_items_are_excluded(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.bootstrap()
    service.save_claim_review(
        "claim-1", ClaimReviewPatch(claim_assessment="ambiguous")
    )
    candidate = service.dataset.missed_candidates[0]
    service.save_missed_review(
        candidate["candidate_id"],
        MissedClaimReviewPatch(decision="needs_domain_review"),
    )
    service.finalize()
    metrics = service.calculate_metrics()
    assert service.reference_path.read_text(encoding="utf-8") == ""
    assert metrics["claim_detection"]["precision_denominator"] == 0
    assert metrics["exclusions"]["prediction_claims_ambiguous"] == 1
    assert metrics["exclusions"]["missed_candidates_needing_domain_review"] == 1


def test_metrics_have_explicit_denominators_and_require_completion(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    service.bootstrap()
    with pytest.raises(ReviewError, match="finalized"):
        service.calculate_metrics()
    service.save_claim_review("claim-1", _complete_claim_patch())
    candidate = service.dataset.missed_candidates[0]
    service.save_missed_review(
        candidate["candidate_id"],
        MissedClaimReviewPatch(
            decision="likely_missed_medication_claim",
            supporting_quote=candidate["turn"]["text"],
        ),
    )
    service.finalize()
    metrics = service.calculate_metrics()
    detection = metrics["claim_detection"]
    assert detection == {
        "tp": 1,
        "fp": 0,
        "fn": 1,
        "precision_denominator": 1,
        "recall_denominator": 2,
        "precision": 1.0,
        "recall": 0.5,
        "f1": 0.6667,
        "matching_strategy": detection["matching_strategy"],
    }
    assert metrics["field_extraction"]["frequency"]["ambiguous_excluded"] == 1
    assert metrics["field_extraction"]["route"]["needs_domain_review_excluded"] == 1
    assert metrics["field_extraction"]["dose_value"]["denominator"] == 1
    assert metrics["hallucination"]["denominator"] == 1


def test_one_prediction_cannot_link_to_multiple_references() -> None:
    duplicate = {
        "reference_id": "reference-1",
        "reference_source": "confirmed_prediction",
        "prediction_claim_id": "claim-1",
    }
    with pytest.raises(ReviewError, match="multiple reference claims"):
        _assert_unique_reference_linkage(
            [duplicate, {**duplicate, "reference_id": "reference-2"}]
        )


def test_human_annotations_never_overwrite_frozen_model_outputs(tmp_path: Path) -> None:
    service = _service(tmp_path)
    before = _hashes(service.dataset.run_directory)
    service.bootstrap()
    service.save_claim_review(
        "claim-1", ClaimReviewPatch(claim_assessment="not_medication_claim")
    )
    after = _hashes(service.dataset.run_directory)
    assert before == after
    assert service.workspace.parent != service.dataset.run_directory.parent


def test_review_workflow_never_constructs_or_calls_an_llm_provider(
    tmp_path: Path, monkeypatch
) -> None:
    from pipeline.providers.anthropic import AnthropicClaimExtractionProvider

    def fail_provider(*args, **kwargs):
        raise AssertionError("Human review must not construct an Anthropic provider")

    monkeypatch.setattr(AnthropicClaimExtractionProvider, "__init__", fail_provider)
    service = _service(tmp_path)
    service.bootstrap()
    service.prediction_queue()
    service.missed_queue()
    service.save_claim_review(
        "claim-1", ClaimReviewPatch(claim_assessment="not_medication_claim")
    )
