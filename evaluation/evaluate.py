"""Evaluate organizer annotations without confusing fixtures with model extraction."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from pipeline.input_contract import EncounterInput
from pipeline.models import PatientClaim
from pipeline.normalization import (
    normalize_dose_unit,
    normalize_frequency,
    normalize_medication_name,
    normalize_route,
    normalize_status,
)
from pipeline.providers import AnthropicClaimExtractionProvider, StubClaimExtractionProvider
from pipeline.providers.base import ClaimExtractionProvider
from pipeline.runner import run_pipeline

FIELD_NORMALIZERS = {
    "status": normalize_status,
    "dose_value": lambda value: float(value) if value is not None else None,
    "dose_unit": normalize_dose_unit,
    "frequency": normalize_frequency,
    "route": normalize_route,
    "adherence_gap": bool,
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _fixture_payload(claims: list[dict[str, Any]]) -> dict[str, Any]:
    payload = []
    for claim in claims:
        span = claim["span"]
        item = {
            key: claim[key]
            for key in (
                "medication_name",
                "status",
                "dose_value",
                "dose_unit",
                "frequency",
                "route",
                "adherence_gap",
            )
            if key in claim
        }
        cue = claim.get("confidence_cue")
        confidence_cues = []
        if cue:
            cue_type = "booster" if claim["confidence_level"] == "emphatic" else "hedge"
            confidence_cues.append(
                {"type": cue_type, "turn_index": span["turn_index"], "quote": cue}
            )
        item.update(
            {
                "confidence_cues": confidence_cues,
                "supporting_quotes": [span],
            }
        )
        if claim.get("adherence_quote"):
            item["adherence_quote"] = {
                "turn_index": span["turn_index"],
                "quote": claim["adherence_quote"],
            }
        payload.append(item)
    return {"claims": payload}


def _match_claims(
    gold: list[dict[str, Any]], predicted: list[PatientClaim]
) -> list[tuple[int, int]]:
    candidates: list[tuple[int, int, int]] = []
    for gold_index, expected in enumerate(gold):
        expected_name = normalize_medication_name(expected["medication_name"])
        for predicted_index, actual in enumerate(predicted):
            if normalize_medication_name(actual.medication_name) != expected_name:
                continue
            field_matches = 0
            for field, normalizer in FIELD_NORMALIZERS.items():
                if field in expected and normalizer(getattr(actual, field)) == normalizer(
                    expected[field]
                ):
                    field_matches += 1
            candidates.append((field_matches, gold_index, predicted_index))
    matched_gold: set[int] = set()
    matched_predicted: set[int] = set()
    matches: list[tuple[int, int]] = []
    for _, gold_index, predicted_index in sorted(candidates, reverse=True):
        if gold_index in matched_gold or predicted_index in matched_predicted:
            continue
        matched_gold.add(gold_index)
        matched_predicted.add(predicted_index)
        matches.append((gold_index, predicted_index))
    return matches


def _ratio(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {
        "correct": numerator,
        "total": denominator,
        "value": round(numerator / denominator, 4) if denominator else None,
    }


def _prf(tp: int, fp: int, fn: int) -> dict[str, int | float | None]:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
    }


def evaluate(
    dataset_path: Path,
    annotation_path: Path,
    provider_mode: str,
) -> dict[str, Any]:
    raw_records = _load_jsonl(dataset_path)
    annotation_document = json.loads(annotation_path.read_text(encoding="utf-8"))
    annotation_records = annotation_document["records"]
    if len(raw_records) != 25 or len(annotation_records) != 25:
        raise ValueError("Organizer evaluation requires exactly 25 source and annotation records.")
    provider: ClaimExtractionProvider | None = None
    if provider_mode == "anthropic":
        provider = AnthropicClaimExtractionProvider()

    annotated_claims = sum(len(item["claims"]) for item in annotation_records)
    records_with_claims = sum(bool(item["claims"]) for item in annotation_records)
    predicted_total = 0
    matched_total = 0
    normalization_correct = 0
    asserted_field_correct = 0
    asserted_field_total = 0
    link_tp = link_fp = link_fn = 0
    divergence_correct = 0
    divergence_total = 0
    expected_relations: Counter[str] = Counter()
    predicted_relations: Counter[str] = Counter()
    errors: list[dict[str, Any]] = []

    for raw, annotated in zip(raw_records, annotation_records, strict=True):
        if raw["id"] != annotated["record_id"]:
            raise ValueError(
                f"Annotation/source identity mismatch at index {annotated['record_index']}."
            )
        encounter = EncounterInput.model_validate(raw)
        claims = annotated["claims"]
        active_provider = (
            StubClaimExtractionProvider(_fixture_payload(claims))
            if provider_mode == "fixture"
            else provider
        )
        if active_provider is None:
            raise ValueError(f"Unsupported provider mode: {provider_mode}")
        report = run_pipeline(encounter, active_provider)
        predicted_total += len(report.claims)
        matches = _match_claims(claims, report.claims)
        matched_total += len(matches)
        for gold_index, predicted_index in matches:
            expected = claims[gold_index]
            actual = report.claims[predicted_index]
            if normalize_medication_name(actual.medication_name) == normalize_medication_name(
                expected["medication_name"]
            ):
                normalization_correct += 1
            for field, normalizer in FIELD_NORMALIZERS.items():
                if field not in expected:
                    continue
                asserted_field_total += 1
                if normalizer(getattr(actual, field)) == normalizer(expected[field]):
                    asserted_field_correct += 1

            expected_paths = set(expected["relevant_evidence_paths"])
            evidence_by_id = {item.evidence_id: item for item in report.record_evidence}
            actual_paths = {
                evidence_by_id[link.evidence_id].source_path
                for link in report.links[actual.claim_id]
            }
            link_tp += len(expected_paths & actual_paths)
            link_fp += len(actual_paths - expected_paths)
            link_fn += len(expected_paths - actual_paths)

            expected_relation = expected["expected_relation"]
            actual_relation = report.divergences[actual.claim_id].relation.value
            expected_relations[expected_relation] += 1
            predicted_relations[actual_relation] += 1
            divergence_total += 1
            if actual_relation == expected_relation:
                divergence_correct += 1
            else:
                errors.append(
                    {
                        "annotation_id": expected["annotation_id"],
                        "stage": "divergence",
                        "expected": expected_relation,
                        "actual": actual_relation,
                        "field_comparisons": [
                            item.model_dump(mode="json")
                            for item in report.divergences[actual.claim_id].field_comparisons
                        ],
                    }
                )

        matched_gold = {gold_index for gold_index, _ in matches}
        for gold_index, expected in enumerate(claims):
            if gold_index not in matched_gold:
                errors.append(
                    {
                        "annotation_id": expected["annotation_id"],
                        "stage": "extraction",
                        "expected": expected["medication_name"],
                        "actual": "missing",
                    }
                )

    extraction = _prf(
        matched_total,
        predicted_total - matched_total,
        annotated_claims - matched_total,
    )
    if provider_mode == "fixture":
        extraction = {
            "status": "not_measured",
            "reason": (
                "Author annotations were injected through the deterministic stub; "
                "this is not transcript extraction evaluation."
            ),
            "annotated_claims": annotated_claims,
        }

    return {
        "dataset": {
            "records_inspected": len(annotation_records),
            "records_with_evaluable_claims": records_with_claims,
            "annotated_claims": annotated_claims,
            "annotation_provenance": annotation_document["annotation_provenance"],
        },
        "provider_mode": provider_mode,
        "extraction": extraction,
        "field_extraction": (
            _ratio(asserted_field_correct, asserted_field_total)
            if provider_mode == "anthropic"
            else {
                "status": "not_measured",
                "reason": "Fixture-provided fields are inputs to the reasoning evaluation.",
                "asserted_fields": asserted_field_total,
            }
        ),
        "reasoning_conditioned_on_author_claims": {
            "medication_normalization": _ratio(normalization_correct, matched_total),
            "evidence_linking": _prf(link_tp, link_fp, link_fn),
            "divergence_classification": _ratio(divergence_correct, divergence_total),
            "expected_relation_distribution": dict(sorted(expected_relations.items())),
            "predicted_relation_distribution": dict(sorted(predicted_relations.items())),
        },
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument(
        "--annotations",
        type=Path,
        default=Path("evaluation/organizer_medication_annotations.json"),
    )
    parser.add_argument("--provider", choices=("fixture", "anthropic"), default="fixture")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.dataset, args.annotations, args.provider)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
