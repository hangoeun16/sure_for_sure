from __future__ import annotations

import json
from pathlib import Path

from evaluation.evaluate import evaluate

ROOT = Path(__file__).resolve().parents[2]
ANNOTATIONS = ROOT / "evaluation" / "organizer_medication_annotations.json"
DATASET = ROOT / "synthetic-ambient-fhir-25" / "synthetic-ambient-fhir-25.jsonl"


def test_annotations_cover_all_records_and_exact_patient_spans() -> None:
    annotations = json.loads(ANNOTATIONS.read_text(encoding="utf-8"))["records"]
    records = [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(annotations) == len(records) == 25
    for annotation, record in zip(annotations, records, strict=True):
        assert annotation["inspected"] is True
        assert annotation["record_id"] == record["id"]
        turns = [line.split(": ", 1)[1] for line in record["transcript"].splitlines()]
        for claim in annotation["claims"]:
            span = claim["span"]
            assert span["quote"] in turns[span["turn_index"]]


def test_fixture_reasoning_evaluation_is_explicitly_not_extraction() -> None:
    result = evaluate(DATASET, ANNOTATIONS, "fixture")
    assert result["dataset"]["records_inspected"] == 25
    assert result["dataset"]["records_with_evaluable_claims"] == 18
    assert result["dataset"]["annotated_claims"] == 43
    assert result["extraction"]["status"] == "not_measured"
    assert (
        result["reasoning_conditioned_on_author_claims"]["medication_normalization"]["total"] == 43
    )
