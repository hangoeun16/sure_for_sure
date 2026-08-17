"""Provider-neutral extraction contract."""

from __future__ import annotations

from typing import Protocol

from pipeline.models import DialogueTurn, ProviderExtractionResult


class ProviderError(RuntimeError):
    pass


class ProviderConfigurationError(ProviderError):
    pass


class ProviderOutputError(ProviderError):
    pass


class ProviderSourceGroundingError(ProviderOutputError):
    pass


class ClaimExtractionProvider(Protocol):
    def extract_claims(
        self, *, transcript: str, turns: list[DialogueTurn]
    ) -> ProviderExtractionResult: ...
