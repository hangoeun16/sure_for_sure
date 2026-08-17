"""Local, transcript-only human review over an immutable Anthropic run."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from backend.config import REPOSITORY_ROOT

DEFAULT_REVIEW_RUN_ID = (
    "20260810T201507769345Z_claude-sonnet-4-6_medication_claim_extraction_v2"
)
DEFAULT_RUNS_ROOT = REPOSITORY_ROOT / "evaluation" / "runs" / "anthropic"
DEFAULT_REVIEW_ROOT = REPOSITORY_ROOT / "evaluation" / "human_review"

REVIEW_FIELDS = (
    "medication_identity",
    "dose_value",
    "dose_unit",
    "frequency",
    "route",
    "status_adherence",
    "negation",
)

_MEDICATION_SIGNAL = re.compile(
    r"\b(?:take|taking|took|stop|stopped|skip|skipped|miss|missed|pill|pills|"
    r"medicine|medication|meds|dose|mg|milligrams?|tablets?|capsules?|refill|"
    r"prescription|prn)\b|\bas needed\b",
    re.IGNORECASE,
)


class ReviewError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimAssessment(StrEnum):
    CORRECT = "correct_claim"
    NOT_CLAIM = "not_medication_claim"
    AMBIGUOUS = "ambiguous"
    NEEDS_DOMAIN_REVIEW = "needs_domain_review"


class QuoteAssessment(StrEnum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    AMBIGUOUS = "ambiguous"


class FieldAssessment(StrEnum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    NOT_STATED = "not_stated_by_patient"
    AMBIGUOUS = "ambiguous"
    NEEDS_DOMAIN_REVIEW = "needs_domain_review"


class CueAssessment(StrEnum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    NO_CUE = "no_cue_should_be_present"
    AMBIGUOUS = "ambiguous"


class DerivedConfidenceAssessment(StrEnum):
    CORRECT = "correct_by_rubric"
    INCORRECT = "incorrect_by_rubric"
    AMBIGUOUS = "ambiguous"


class HallucinationAssessment(StrEnum):
    NO = "no"
    YES = "yes"
    AMBIGUOUS = "ambiguous"


class MissedClaimAssessment(StrEnum):
    COVERED = "already_covered"
    LIKELY_MISSED = "likely_missed_medication_claim"
    NOT_CLAIM = "not_medication_claim"
    AMBIGUOUS = "ambiguous"
    NEEDS_DOMAIN_REVIEW = "needs_domain_review"


class ClaimReviewPatch(StrictModel):
    claim_assessment: ClaimAssessment | None = None
    supporting_quote: QuoteAssessment | None = None
    field_reviews: dict[str, FieldAssessment] | None = None
    confidence_cues: CueAssessment | None = None
    derived_confidence: DerivedConfidenceAssessment | None = None
    hallucination: HallucinationAssessment | None = None
    hallucination_notes: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)


class MissedClaimReviewPatch(StrictModel):
    decision: MissedClaimAssessment | None = None
    supporting_quote: str | None = Field(default=None, max_length=4000)
    medication_name_as_spoken: str | None = Field(default=None, max_length=500)
    dose_as_spoken: str | None = Field(default=None, max_length=500)
    frequency_as_spoken: str | None = Field(default=None, max_length=500)
    status_adherence_as_spoken: str | None = Field(default=None, max_length=500)
    confidence_cues_as_spoken: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)


class ProgressPatch(StrictModel):
    queue: str
    item_id: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in values),
        encoding="utf-8",
    )
    temporary.replace(path)


class FrozenReviewDataset:
    """Read-only projection of a persisted live run for human review."""

    def __init__(self, run_directory: str | Path) -> None:
        self.run_directory = Path(run_directory).resolve()
        if not self.run_directory.is_dir():
            raise ReviewError(f"Frozen run directory does not exist: {self.run_directory}")
        manifest_path = self.run_directory / "manifest.json"
        downstream_path = self.run_directory / "downstream_results.jsonl"
        if not manifest_path.is_file() or not downstream_path.is_file():
            raise ReviewError("Frozen run is missing its manifest or downstream results.")
        self.manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        if self.manifest.get("run_id") != self.run_directory.name:
            raise ReviewError("Frozen run manifest does not match its directory name.")
        self.records = sorted(_read_jsonl(downstream_path), key=lambda item: item["record_index"])
        self._record_by_id = {str(item["record_id"]): item for item in self.records}
        self.predictions = self._build_predictions()
        self.prediction_by_id = {str(item["claim_id"]): item for item in self.predictions}
        self.missed_candidates = self._build_missed_candidates()
        self.candidate_by_id = {
            str(item["candidate_id"]): item for item in self.missed_candidates
        }

    def _build_predictions(self) -> list[dict[str, Any]]:
        predictions: list[dict[str, Any]] = []
        for record in self.records:
            output = record["pipeline_output"]
            turns = output["turns"]
            for claim in output["claims"]:
                supporting_turns = {
                    int(span["turn_index"]) for span in claim["supporting_spans"]
                }
                context_indexes = {
                    index
                    for turn_index in supporting_turns
                    for index in range(max(0, turn_index - 2), min(len(turns), turn_index + 3))
                }
                predictions.append(
                    {
                        "claim_id": claim["claim_id"],
                        "record_id": record["record_id"],
                        "record_index": record["record_index"],
                        "encounter_number": int(record["record_index"]) + 1,
                        "encounter_count": len(self.records),
                        "claim": claim,
                        "context_turns": [turns[index] for index in sorted(context_indexes)],
                        "supporting_turn_indexes": sorted(supporting_turns),
                    }
                )
        predictions.sort(
            key=lambda item: (
                int(item["record_index"]),
                int(item["claim"]["first_turn"]),
                str(item["claim_id"]),
            )
        )
        for index, item in enumerate(predictions):
            item["queue_index"] = index
            item["queue_total"] = len(predictions)
        return predictions

    def _build_missed_candidates(self) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for record in self.records:
            output = record["pipeline_output"]
            covered_turns = {
                int(span["turn_index"])
                for claim in output["claims"]
                for span in claim["supporting_spans"]
            }
            evidence_names = {
                str(item.get("medication_name", "")).strip().lower()
                for item in output.get("record_evidence", [])
                if str(item.get("medication_name", "")).strip()
            }
            for turn in output["turns"]:
                if turn["speaker"] != "PT" or int(turn["index"]) in covered_turns:
                    continue
                text = str(turn["text"])
                lexical = sorted(
                    {
                        match.group(0).lower()
                        for match in _MEDICATION_SIGNAL.finditer(text)
                    }
                )
                lowered = text.lower()
                medication_names = sorted(
                    name for name in evidence_names if len(name) >= 3 and name in lowered
                )
                if not lexical and not medication_names:
                    continue
                material = f"{record['record_id']}|{turn['index']}|{text}"
                candidate_id = "candidate-" + hashlib.sha256(material.encode()).hexdigest()[:16]
                candidates.append(
                    {
                        "candidate_id": candidate_id,
                        "record_id": record["record_id"],
                        "record_index": record["record_index"],
                        "encounter_number": int(record["record_index"]) + 1,
                        "encounter_count": len(self.records),
                        "turn": turn,
                        "signals": lexical
                        + [f"medication name: {name}" for name in medication_names],
                    }
                )
        candidates.sort(key=lambda item: (int(item["record_index"]), int(item["turn"]["index"])))
        for index, item in enumerate(candidates):
            item["queue_index"] = index
            item["queue_total"] = len(candidates)
        return candidates

    def transcript(self, record_id: str) -> dict[str, Any]:
        record = self._record_by_id.get(record_id)
        if record is None:
            raise ReviewError(f"Unknown record ID: {record_id}")
        return {
            "record_id": record_id,
            "record_index": record["record_index"],
            "turns": record["pipeline_output"]["turns"],
        }


class HumanReviewService:
    """Autosaved review workspace that never writes into the source run."""

    def __init__(
        self,
        *,
        run_id: str = DEFAULT_REVIEW_RUN_ID,
        runs_root: str | Path = DEFAULT_RUNS_ROOT,
        review_root: str | Path = DEFAULT_REVIEW_ROOT,
    ) -> None:
        if Path(run_id).name != run_id:
            raise ReviewError("Review run ID must be a directory name, not a path.")
        self.run_id = run_id
        self.dataset = FrozenReviewDataset(Path(runs_root) / run_id)
        self.workspace = Path(review_root).resolve() / run_id
        if (
            self.workspace == self.dataset.run_directory
            or self.dataset.run_directory in self.workspace.parents
        ):
            raise ReviewError("Human review workspace must be separate from the frozen run.")
        self.manifest_path = self.workspace / "review_manifest.json"
        self.claim_reviews_path = self.workspace / "claim_reviews.jsonl"
        self.missed_reviews_path = self.workspace / "missed_claim_reviews.jsonl"
        self.reference_path = self.workspace / "reference_claims.jsonl"
        self.progress_path = self.workspace / "review_progress.json"
        self.metrics_path = self.workspace / "metrics.json"

    def ensure_workspace(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            source = self.dataset.manifest
            _write_json(
                self.manifest_path,
                {
                    "source_run_id": self.run_id,
                    "model": source.get("model"),
                    "prompt_version": source.get("prompt_version"),
                    "prompt_hash": source.get("prompt_hash"),
                    "dataset": source.get("dataset_file"),
                    "dataset_sha256": source.get("dataset_sha256"),
                    "review_scope": "transcript_observable_medication_claim_extraction",
                    "review_status": "not_started",
                    "reviewer_type": "non_clinician_author",
                    "created_at": _now(),
                    "completed_at": None,
                },
            )
        if not self.claim_reviews_path.exists():
            _write_jsonl(self.claim_reviews_path, [])
        if not self.missed_reviews_path.exists():
            _write_jsonl(self.missed_reviews_path, [])
        if not self.reference_path.exists():
            _write_jsonl(self.reference_path, [])
        if not self.progress_path.exists():
            _write_json(
                self.progress_path,
                {
                    "last_queue": "predictions",
                    "last_item_id": (
                        self.dataset.predictions[0]["claim_id"]
                        if self.dataset.predictions
                        else None
                    ),
                    "updated_at": _now(),
                },
            )

    def bootstrap(self) -> dict[str, Any]:
        self.ensure_workspace()
        return {
            "manifest": self._manifest(),
            "progress": self.progress(),
            "prediction_count": len(self.dataset.predictions),
            "missed_candidate_count": len(self.dataset.missed_candidates),
            "workspace": str(self.workspace),
        }

    def prediction_queue(self) -> list[dict[str, Any]]:
        self.ensure_workspace()
        reviews = self._claim_review_map()
        return [
            {**item, "review": reviews.get(str(item["claim_id"]))}
            for item in self.dataset.predictions
        ]

    def missed_queue(self) -> list[dict[str, Any]]:
        self.ensure_workspace()
        reviews = self._missed_review_map()
        return [
            {**item, "review": reviews.get(str(item["candidate_id"]))}
            for item in self.dataset.missed_candidates
        ]

    def transcript(self, record_id: str) -> dict[str, Any]:
        return self.dataset.transcript(record_id)

    def save_claim_review(
        self, claim_id: str, patch: ClaimReviewPatch
    ) -> dict[str, Any]:
        self.ensure_workspace()
        prediction = self.dataset.prediction_by_id.get(claim_id)
        if prediction is None:
            raise ReviewError(f"Unknown claim ID: {claim_id}")
        reviews = self._claim_review_map()
        current = reviews.get(
            claim_id,
            {
                "source_run_id": self.run_id,
                "record_id": prediction["record_id"],
                "record_index": prediction["record_index"],
                "claim_id": claim_id,
            },
        )
        updates = patch.model_dump(mode="json", exclude_unset=True)
        if "field_reviews" in updates and updates["field_reviews"] is not None:
            invalid = set(updates["field_reviews"]) - set(REVIEW_FIELDS)
            if invalid:
                raise ReviewError(f"Unknown review fields: {sorted(invalid)}")
        saved = {**current, **updates, "updated_at": _now()}
        reviews[claim_id] = saved
        _write_jsonl(
            self.claim_reviews_path,
            sorted(reviews.values(), key=lambda item: (item["record_index"], item["claim_id"])),
        )
        self._mark_active("predictions", claim_id)
        return {**saved, "complete": _claim_review_complete(saved)}

    def save_missed_review(
        self, candidate_id: str, patch: MissedClaimReviewPatch
    ) -> dict[str, Any]:
        self.ensure_workspace()
        candidate = self.dataset.candidate_by_id.get(candidate_id)
        if candidate is None:
            raise ReviewError(f"Unknown missed-claim candidate ID: {candidate_id}")
        reviews = self._missed_review_map()
        current = reviews.get(
            candidate_id,
            {
                "source_run_id": self.run_id,
                "record_id": candidate["record_id"],
                "record_index": candidate["record_index"],
                "candidate_id": candidate_id,
                "turn_index": candidate["turn"]["index"],
            },
        )
        updates = patch.model_dump(mode="json", exclude_unset=True)
        quote = updates.get("supporting_quote")
        if quote and quote not in candidate["turn"]["text"]:
            raise ReviewError("Missed-claim supporting quote must be verbatim patient speech.")
        saved = {**current, **updates, "updated_at": _now()}
        reviews[candidate_id] = saved
        _write_jsonl(
            self.missed_reviews_path,
            sorted(
                reviews.values(),
                key=lambda item: (item["record_index"], item["turn_index"]),
            ),
        )
        self._mark_active("missed", candidate_id)
        return {**saved, "complete": _missed_review_complete(saved)}

    def save_progress(self, patch: ProgressPatch) -> dict[str, Any]:
        self.ensure_workspace()
        if patch.queue == "predictions":
            valid = patch.item_id in self.dataset.prediction_by_id
        elif patch.queue == "missed":
            valid = patch.item_id in self.dataset.candidate_by_id
        else:
            raise ReviewError("Review queue must be 'predictions' or 'missed'.")
        if not valid:
            raise ReviewError("Progress item does not belong to the selected review queue.")
        _write_json(
            self.progress_path,
            {"last_queue": patch.queue, "last_item_id": patch.item_id, "updated_at": _now()},
        )
        return self.progress()

    def progress(self) -> dict[str, Any]:
        self.ensure_workspace()
        claim_reviews = self._claim_review_map()
        missed_reviews = self._missed_review_map()
        stored = json.loads(self.progress_path.read_text(encoding="utf-8"))
        prediction_complete = sum(
            _claim_review_complete(claim_reviews.get(str(item["claim_id"]), {}))
            for item in self.dataset.predictions
        )
        missed_complete = sum(
            _missed_review_complete(missed_reviews.get(str(item["candidate_id"]), {}))
            for item in self.dataset.missed_candidates
        )
        return {
            **stored,
            "predictions": {
                "complete": prediction_complete,
                "total": len(self.dataset.predictions),
            },
            "missed_candidates": {
                "complete": missed_complete,
                "total": len(self.dataset.missed_candidates),
            },
            "all_complete": (
                prediction_complete == len(self.dataset.predictions)
                and missed_complete == len(self.dataset.missed_candidates)
            ),
        }

    def finalize(self) -> dict[str, Any]:
        self.ensure_workspace()
        progress = self.progress()
        if not progress["all_complete"]:
            raise ReviewError("Both review queues must be 100% complete before finalization.")
        references = self._build_reference_claims()
        _assert_unique_reference_linkage(references)
        _write_jsonl(self.reference_path, references)
        manifest = self._manifest()
        manifest.update({"review_status": "completed", "completed_at": _now()})
        _write_json(self.manifest_path, manifest)
        return {
            "review_status": "completed",
            "reference_claims": len(references),
            "reference_path": str(self.reference_path),
        }

    def calculate_metrics(self) -> dict[str, Any]:
        self.ensure_workspace()
        if self._manifest().get("review_status") != "completed":
            raise ReviewError("Metrics are unavailable until the human review is finalized.")
        claim_reviews = list(self._claim_review_map().values())
        missed_reviews = list(self._missed_review_map().values())
        predictions = self.dataset.prediction_by_id

        tp = sum(item.get("claim_assessment") == ClaimAssessment.CORRECT for item in claim_reviews)
        fp = sum(
            item.get("claim_assessment") == ClaimAssessment.NOT_CLAIM
            for item in claim_reviews
        )
        fn = sum(
            item.get("decision") == MissedClaimAssessment.LIKELY_MISSED
            for item in missed_reviews
        )
        claim_detection = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision_denominator": tp + fp,
            "recall_denominator": tp + fn,
            "precision": _ratio(tp, tp + fp),
            "recall": _ratio(tp, tp + fn),
            "f1": _f1(tp, fp, fn),
            "matching_strategy": (
                "Direct human linkage: confirmed predictions retain one source claim ID; "
                "missed claims retain one uncovered patient-turn candidate ID."
            ),
        }

        confirmed = [
            item
            for item in claim_reviews
            if item.get("claim_assessment") == ClaimAssessment.CORRECT
        ]
        field_metrics = {
            field: _field_metric(field, confirmed, predictions) for field in REVIEW_FIELDS
        }
        field_metrics["supporting_span"] = _simple_metric(
            [item.get("supporting_quote") for item in confirmed],
            correct_values={QuoteAssessment.CORRECT},
            incorrect_values={QuoteAssessment.INCORRECT},
            ambiguous_values={QuoteAssessment.AMBIGUOUS},
        )
        field_metrics["confidence_cues"] = _cue_metric(confirmed, predictions)
        field_metrics["derived_confidence"] = _simple_metric(
            [item.get("derived_confidence") for item in confirmed],
            correct_values={DerivedConfidenceAssessment.CORRECT},
            incorrect_values={DerivedConfidenceAssessment.INCORRECT},
            ambiguous_values={DerivedConfidenceAssessment.AMBIGUOUS},
        )

        hallucination_values = [item.get("hallucination") for item in confirmed]
        hallucination_yes = sum(
            value == HallucinationAssessment.YES for value in hallucination_values
        )
        hallucination_no = sum(
            value == HallucinationAssessment.NO for value in hallucination_values
        )
        metrics = {
            "source_run_id": self.run_id,
            "evaluation_scope": "human-reviewed transcript-observable extraction only",
            "claim_detection": claim_detection,
            "field_extraction": field_metrics,
            "hallucination": {
                "yes": hallucination_yes,
                "no": hallucination_no,
                "ambiguous_excluded": sum(
                    value == HallucinationAssessment.AMBIGUOUS for value in hallucination_values
                ),
                "denominator": hallucination_yes + hallucination_no,
                "percentage": _ratio(
                    hallucination_yes, hallucination_yes + hallucination_no
                ),
            },
            "exclusions": {
                "prediction_claims_ambiguous": sum(
                    item.get("claim_assessment") == ClaimAssessment.AMBIGUOUS
                    for item in claim_reviews
                ),
                "prediction_claims_needing_domain_review": sum(
                    item.get("claim_assessment") == ClaimAssessment.NEEDS_DOMAIN_REVIEW
                    for item in claim_reviews
                ),
                "missed_candidates_ambiguous": sum(
                    item.get("decision") == MissedClaimAssessment.AMBIGUOUS
                    for item in missed_reviews
                ),
                "missed_candidates_needing_domain_review": sum(
                    item.get("decision") == MissedClaimAssessment.NEEDS_DOMAIN_REVIEW
                    for item in missed_reviews
                ),
            },
            "generated_at": _now(),
        }
        _write_json(self.metrics_path, metrics)
        return metrics

    def _build_reference_claims(self) -> list[dict[str, Any]]:
        references: list[dict[str, Any]] = []
        for review in self._claim_review_map().values():
            if review.get("claim_assessment") != ClaimAssessment.CORRECT:
                continue
            prediction = self.dataset.prediction_by_id[str(review["claim_id"])]
            claim = prediction["claim"]
            references.append(
                {
                    "reference_id": f"reference-prediction-{review['claim_id']}",
                    "reference_source": "confirmed_prediction",
                    "source_run_id": self.run_id,
                    "record_id": review["record_id"],
                    "record_index": review["record_index"],
                    "prediction_claim_id": review["claim_id"],
                    "supporting_spans": claim["supporting_spans"],
                    "prediction": {
                        key: claim.get(key)
                        for key in (
                            "medication_name",
                            "dose_value",
                            "dose_unit",
                            "frequency",
                            "route",
                            "status",
                            "adherence_gap",
                            "negated",
                            "confidence",
                        )
                    },
                    "human_review": review,
                }
            )
        for review in self._missed_review_map().values():
            if review.get("decision") != MissedClaimAssessment.LIKELY_MISSED:
                continue
            candidate = self.dataset.candidate_by_id[str(review["candidate_id"])]
            turn = candidate["turn"]
            quote = str(review["supporting_quote"])
            local_start = str(turn["text"]).find(quote)
            references.append(
                {
                    "reference_id": f"reference-missed-{review['candidate_id']}",
                    "reference_source": "human_identified_missed_claim",
                    "source_run_id": self.run_id,
                    "record_id": review["record_id"],
                    "record_index": review["record_index"],
                    "candidate_id": review["candidate_id"],
                    "supporting_spans": [
                        {
                            "turn_index": turn["index"],
                            "start_char": int(turn["start_char"]) + local_start,
                            "end_char": int(turn["start_char"]) + local_start + len(quote),
                            "text": quote,
                        }
                    ],
                    "transcript_observable_fields": {
                        "medication_name_as_spoken": review.get(
                            "medication_name_as_spoken"
                        )
                        or "unspecified",
                        "dose_as_spoken": review.get("dose_as_spoken") or "unspecified",
                        "frequency_as_spoken": review.get("frequency_as_spoken")
                        or "unspecified",
                        "status_adherence_as_spoken": review.get(
                            "status_adherence_as_spoken"
                        )
                        or "unspecified",
                        "confidence_cues_as_spoken": review.get(
                            "confidence_cues_as_spoken"
                        )
                        or "unspecified",
                    },
                    "human_review": review,
                }
            )
        return sorted(
            references,
            key=lambda item: (int(item["record_index"]), str(item["reference_id"])),
        )

    def _claim_review_map(self) -> dict[str, dict[str, Any]]:
        return {
            str(item["claim_id"]): item for item in _read_jsonl(self.claim_reviews_path)
        }

    def _missed_review_map(self) -> dict[str, dict[str, Any]]:
        return {
            str(item["candidate_id"]): item
            for item in _read_jsonl(self.missed_reviews_path)
        }

    def _manifest(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json.loads(self.manifest_path.read_text(encoding="utf-8")),
        )

    def _mark_active(self, queue: str, item_id: str) -> None:
        manifest = self._manifest()
        if manifest.get("review_status") == "completed":
            _write_jsonl(self.reference_path, [])
            if self.metrics_path.exists():
                self.metrics_path.unlink()
        manifest.update({"review_status": "in_progress", "completed_at": None})
        _write_json(self.manifest_path, manifest)
        _write_json(
            self.progress_path,
            {"last_queue": queue, "last_item_id": item_id, "updated_at": _now()},
        )


def _claim_review_complete(review: dict[str, Any]) -> bool:
    assessment = review.get("claim_assessment")
    if assessment is None:
        return False
    if assessment != ClaimAssessment.CORRECT:
        return True
    fields = review.get("field_reviews") or {}
    return bool(
        review.get("supporting_quote")
        and set(fields) == set(REVIEW_FIELDS)
        and review.get("confidence_cues")
        and review.get("derived_confidence")
        and review.get("hallucination")
    )


def _missed_review_complete(review: dict[str, Any]) -> bool:
    decision = review.get("decision")
    if decision is None:
        return False
    if decision != MissedClaimAssessment.LIKELY_MISSED:
        return True
    return bool(str(review.get("supporting_quote") or "").strip())


def _assert_unique_reference_linkage(references: list[dict[str, Any]]) -> None:
    reference_ids = [str(item["reference_id"]) for item in references]
    if len(reference_ids) != len(set(reference_ids)):
        raise ReviewError("Reference IDs must be unique.")
    prediction_ids = [
        str(item["prediction_claim_id"])
        for item in references
        if item["reference_source"] == "confirmed_prediction"
    ]
    if len(prediction_ids) != len(set(prediction_ids)):
        raise ReviewError("One prediction cannot link to multiple reference claims.")


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _f1(tp: int, fp: int, fn: int) -> float | None:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    if precision is None or recall is None or precision + recall == 0:
        return None
    return round(2 * precision * recall / (precision + recall), 4)


def _simple_metric(
    values: list[Any],
    *,
    correct_values: set[Any],
    incorrect_values: set[Any],
    ambiguous_values: set[Any],
) -> dict[str, Any]:
    correct = sum(value in correct_values for value in values)
    incorrect = sum(value in incorrect_values for value in values)
    ambiguous = sum(value in ambiguous_values for value in values)
    denominator = correct + incorrect
    return {
        "correct": correct,
        "incorrect": incorrect,
        "ambiguous_excluded": ambiguous,
        "denominator": denominator,
        "accuracy": _ratio(correct, denominator),
    }


def _prediction_has_value(field: str, claim: dict[str, Any]) -> bool:
    if field == "medication_identity":
        return bool(claim.get("medication_name"))
    if field == "status_adherence":
        return bool(claim.get("status") is not None or claim.get("adherence_gap"))
    if field == "negation":
        return bool(claim.get("negated"))
    return claim.get(field) is not None


def _field_metric(
    field: str,
    reviews: list[dict[str, Any]],
    predictions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    correct = 0
    incorrect = 0
    not_stated = 0
    ambiguous = 0
    domain = 0
    for review in reviews:
        decision = (review.get("field_reviews") or {}).get(field)
        if decision == FieldAssessment.CORRECT:
            correct += 1
        elif decision == FieldAssessment.INCORRECT:
            incorrect += 1
        elif decision == FieldAssessment.NOT_STATED:
            not_stated += 1
            prediction = predictions[str(review["claim_id"])]["claim"]
            if _prediction_has_value(field, prediction):
                incorrect += 1
            else:
                correct += 1
        elif decision == FieldAssessment.AMBIGUOUS:
            ambiguous += 1
        elif decision == FieldAssessment.NEEDS_DOMAIN_REVIEW:
            domain += 1
    denominator = correct + incorrect
    return {
        "correct": correct,
        "incorrect": incorrect,
        "not_stated_reviews": not_stated,
        "ambiguous_excluded": ambiguous,
        "needs_domain_review_excluded": domain,
        "denominator": denominator,
        "accuracy": _ratio(correct, denominator),
    }


def _cue_metric(
    reviews: list[dict[str, Any]], predictions: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    correct = 0
    incorrect = 0
    no_cue = 0
    ambiguous = 0
    for review in reviews:
        decision = review.get("confidence_cues")
        if decision == CueAssessment.CORRECT:
            correct += 1
        elif decision == CueAssessment.INCORRECT:
            incorrect += 1
        elif decision == CueAssessment.NO_CUE:
            no_cue += 1
            cues = predictions[str(review["claim_id"])]["claim"]["confidence"]["cues"]
            if cues:
                incorrect += 1
            else:
                correct += 1
        elif decision == CueAssessment.AMBIGUOUS:
            ambiguous += 1
    denominator = correct + incorrect
    return {
        "correct": correct,
        "incorrect": incorrect,
        "no_cue_reviews": no_cue,
        "ambiguous_excluded": ambiguous,
        "denominator": denominator,
        "accuracy": _ratio(correct, denominator),
    }
