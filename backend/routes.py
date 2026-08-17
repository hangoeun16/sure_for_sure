"""Thin HTTP routes; all reasoning stays in pipeline.runner."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pipeline.input_contract import EncounterInput
from pipeline.models import EncounterAnalysis, SourceProvenance
from pipeline.providers import (
    AnthropicClaimExtractionProvider,
    StubClaimExtractionProvider,
)
from pipeline.providers.base import ClaimExtractionProvider
from pipeline.runner import run_pipeline

from backend.config import Settings
from backend.repository import (
    EncounterRepository,
    RepositoryError,
    canonical_record_hash,
)

router = APIRouter()


def _settings() -> Settings:
    return Settings.from_environment()


def _repository(settings: Settings) -> EncounterRepository:
    if settings.sure_for_sure_dataset is None:
        raise HTTPException(status_code=503, detail="SURE_FOR_SURE_DATASET is not configured.")
    return EncounterRepository(settings.sure_for_sure_dataset)


def _provider(settings: Settings, encounter: EncounterInput) -> ClaimExtractionProvider:
    if settings.sure_for_sure_provider == "anthropic":
        return AnthropicClaimExtractionProvider(
            api_key=settings.anthropic_api_key,
            model=settings.sure_for_sure_anthropic_model,
        )
    fixture = encounter.metadata.get("claim_extraction")
    return StubClaimExtractionProvider(fixture if isinstance(fixture, dict) else None)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/encounters")
def list_encounters() -> list[dict[str, Any]]:
    try:
        return _repository(_settings()).listing()
    except RepositoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/encounters/{record_id}", response_model=EncounterInput)
def get_encounter(record_id: str) -> EncounterInput:
    try:
        return _repository(_settings()).get_by_id(record_id)[0]
    except RepositoryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/analyze", response_model=EncounterAnalysis)
def analyze_encounter(encounter: EncounterInput) -> EncounterAnalysis:
    settings = _settings()
    dumped = encounter.model_dump(mode="json")
    source = SourceProvenance(
        source_dataset="api",
        source_file="request-body",
        source_record_id=encounter.id,
        source_record_index=0,
        source_sha256=canonical_record_hash(dumped),
        record_sha256=canonical_record_hash(dumped),
    )
    return run_pipeline(encounter, _provider(settings, encounter), source=source)


@router.post("/analyze/{record_id}", response_model=EncounterAnalysis)
def analyze_configured_encounter(record_id: str) -> EncounterAnalysis:
    settings = _settings()
    try:
        encounter, source = _repository(settings).get_by_id(record_id)
    except RepositoryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return run_pipeline(encounter, _provider(settings, encounter), source=source)
