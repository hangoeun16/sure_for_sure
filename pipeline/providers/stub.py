"""Credential-free deterministic provider for examples, tests, and UI work."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from pipeline.models import DialogueTurn, ProviderExtractionResult
from pipeline.providers.base import ProviderOutputError


class StubClaimExtractionProvider:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = deepcopy(response or {"claims": []})
        self.calls = 0

    def extract_claims(
        self, *, transcript: str, turns: list[DialogueTurn]
    ) -> ProviderExtractionResult:
        self.calls += 1
        payload = deepcopy(self.response)
        payload["metadata"] = {
            "provider": "stub",
            "model": "fixture-schema-v2",
            "request_id": f"stub-{self.calls}",
            "schema_version": "claim-extraction-v2",
            "attempts": 1,
            "usage": {},
        }
        try:
            return ProviderExtractionResult.model_validate(payload)
        except ValidationError as exc:
            raise ProviderOutputError(f"Stub output failed schema validation: {exc}") from exc
