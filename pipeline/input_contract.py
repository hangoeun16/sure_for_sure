"""Typed boundary for organizer-compatible encounter records."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EncounterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    metadata: dict[str, Any]
    patient_context: dict[str, Any]
    encounter_fhir: dict[str, Any]
    transcript: str = Field(min_length=1)
    note: str
    after_visit_summary: str
    after_visit_summary_provenance: dict[str, Any]
