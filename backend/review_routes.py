"""Local-only HTTP interface for transcript-observable human review."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, HTTPException

from backend.human_review import (
    DEFAULT_REVIEW_ROOT,
    DEFAULT_REVIEW_RUN_ID,
    DEFAULT_RUNS_ROOT,
    ClaimReviewPatch,
    HumanReviewService,
    MissedClaimReviewPatch,
    ProgressPatch,
    ReviewError,
)

router = APIRouter()


def _service() -> HumanReviewService:
    return HumanReviewService(
        run_id=os.getenv("SURE_FOR_SURE_REVIEW_RUN_ID", DEFAULT_REVIEW_RUN_ID),
        runs_root=Path(os.getenv("SURE_FOR_SURE_REVIEW_RUNS_ROOT", str(DEFAULT_RUNS_ROOT))),
        review_root=Path(
            os.getenv("SURE_FOR_SURE_HUMAN_REVIEW_ROOT", str(DEFAULT_REVIEW_ROOT))
        ),
    )


def _call(method: str, *args: Any) -> Any:
    try:
        return getattr(_service(), method)(*args)
    except ReviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/bootstrap")
def bootstrap() -> dict[str, Any]:
    return cast(dict[str, Any], _call("bootstrap"))


@router.get("/predictions")
def predictions() -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], _call("prediction_queue"))


@router.patch("/predictions/{claim_id}")
def save_prediction(claim_id: str, patch: ClaimReviewPatch) -> dict[str, Any]:
    return cast(dict[str, Any], _call("save_claim_review", claim_id, patch))


@router.get("/missed-candidates")
def missed_candidates() -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], _call("missed_queue"))


@router.patch("/missed-candidates/{candidate_id}")
def save_missed_candidate(
    candidate_id: str, patch: MissedClaimReviewPatch
) -> dict[str, Any]:
    return cast(
        dict[str, Any], _call("save_missed_review", candidate_id, patch)
    )


@router.get("/transcripts/{record_id}")
def transcript(record_id: str) -> dict[str, Any]:
    return cast(dict[str, Any], _call("transcript", record_id))


@router.get("/progress")
def progress() -> dict[str, Any]:
    return cast(dict[str, Any], _call("progress"))


@router.patch("/progress")
def save_progress(patch: ProgressPatch) -> dict[str, Any]:
    return cast(dict[str, Any], _call("save_progress", patch))


@router.post("/finalize")
def finalize() -> dict[str, Any]:
    return cast(dict[str, Any], _call("finalize"))
