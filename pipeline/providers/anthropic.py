"""Anthropic structured claim extraction adapter."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from pipeline.models import (
    DialogueTurn,
    ExtractorMetadata,
    Model,
    ProviderConfidenceCue,
    ProviderExtractionResult,
)
from pipeline.providers.base import ProviderConfigurationError, ProviderOutputError

PROMPT_VERSION = "medication_claim_extraction_v2"
MAX_TOKENS = 4096
TEMPERATURE = 0
TIMEOUT_SECONDS = 60.0
RETRY_LIMIT = 1

_SYSTEM = """Extract only medication claims made or explicitly confirmed by the patient.
Clinician speech may provide local context for a short patient answer, but is never a
claim by itself. Return a separate claim per medication. Every supporting quote,
negation quote, adherence quote, and confidence cue must be copied verbatim with its turn
index. Include at least one patient quote for every claim. Return confidence_cues only
for explicit linguistic evidence in patient supporting speech: booster (always, never,
definitely, for sure, I know, 100%, no problems at all), hedge (maybe, I think, I guess,
not sure, could be, probably, I don't know, I'm uncertain), self_justification, or
authority. Do not treat every day, everyday, daily, still, each time, vague medication
descriptions, missing dose/frequency/name, or missing chart evidence as confidence cues.
Do not treat a couple of years, really, a little, or kind of as hedges by themselves.
Return an empty confidence_cues list for an ordinary assertion with no explicit cue.
Python detects transcribed ellipsis hesitation deterministically, so do not add
punctuation-only hesitation cues. Do not compare against the chart, score CED, route, or
suppress findings. Return only the requested structured output."""

_PLACEHOLDER_KEYS = {
    "xxxxx",
    "your_api_key_here",
    "your_anthropic_api_key_here",
    "anthropic_api_key",
    "placeholder",
    "replace_me",
}


@dataclass
class AnthropicAttemptTrace:
    attempt: int
    latency_ms: int
    request_id: str | None = None
    model: str | None = None
    raw_output: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    schema_valid: bool = False
    error_category: str | None = None
    status_code: int | None = None
    error_message: str | None = None


@dataclass
class AnthropicCallTrace:
    attempts: list[AnthropicAttemptTrace] = field(default_factory=list)
    validated_output: dict[str, Any] | None = None

    @property
    def usage(self) -> dict[str, int]:
        return {
            "input_tokens": sum(item.input_tokens for item in self.attempts),
            "output_tokens": sum(item.output_tokens for item in self.attempts),
        }

    @property
    def latency_ms(self) -> int:
        return sum(item.latency_ms for item in self.attempts)


class AnthropicQuote(Model):
    """Strict quote representation accepted by Anthropic structured outputs."""

    turn_index: int
    quote: str


class AnthropicProviderClaim(Model):
    """Anthropic-facing claim payload converted into the production provider model."""

    medication_name: str
    status: str | None = None
    dose_value: float | None = None
    dose_unit: str | None = None
    frequency: str | None = None
    route: str | None = None
    negated: bool = False
    negation_quote: AnthropicQuote | None = None
    confidence_cues: list[ProviderConfidenceCue]
    supporting_quotes: list[AnthropicQuote]
    adherence_gap: bool = False
    adherence_quote: AnthropicQuote | None = None


class AnthropicExtractionPayload(Model):
    claims: list[AnthropicProviderClaim]


def provider_output_schema() -> dict[str, Any]:
    schema = AnthropicExtractionPayload.model_json_schema()
    validate_anthropic_schema(schema)
    return schema


def validate_anthropic_schema(schema: dict[str, Any]) -> None:
    """Reject open or schema-valued object properties before an API request is sent."""
    errors: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                if not isinstance(node.get("properties"), dict):
                    errors.append(f"{path}: object schema must define explicit properties")
                if node.get("additionalProperties") is not False:
                    errors.append(f"{path}: additionalProperties must be false")
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(schema, "$")
    if errors:
        raise ProviderConfigurationError(
            "Anthropic output schema is incompatible: " + "; ".join(errors)
        )


def prompt_hash() -> str:
    """Hash the frozen prompt template and schema, excluding encounter-specific text."""
    material = {
        "system": _SYSTEM,
        "user_template": {
            "transcript": "<runtime transcript>",
            "turns": "<runtime dialogue turns>",
        },
        "output_schema": provider_output_schema(),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def is_placeholder_api_key(value: str | None) -> bool:
    if value is None or not value.strip():
        return False
    normalized = value.strip().lower()
    return (
        normalized in _PLACEHOLDER_KEYS
        or normalized.startswith("<")
        or normalized.endswith(">")
        or "placeholder" in normalized
        or "replace" in normalized
        or len(set(normalized)) == 1
    )


class AnthropicClaimExtractionProvider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: Any | None = None,
        timeout_seconds: float = TIMEOUT_SECONDS,
        retry_limit: int = RETRY_LIMIT,
    ) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model or os.getenv("SURE_FOR_SURE_ANTHROPIC_MODEL")
        self.timeout_seconds = timeout_seconds
        self.retry_limit = retry_limit
        self._client = client
        self.last_trace = AnthropicCallTrace()
        if not self.api_key:
            raise ProviderConfigurationError(
                "Anthropic provider requested, but ANTHROPIC_API_KEY is not configured. "
                "Set it in .env before running the live provider."
            )
        if is_placeholder_api_key(self.api_key):
            raise ProviderConfigurationError(
                "Anthropic provider requested, but ANTHROPIC_API_KEY is still a placeholder. "
                "Replace the placeholder in .env before running the live provider."
            )
        if not self.model:
            raise ProviderConfigurationError(
                "SURE_FOR_SURE_ANTHROPIC_MODEL is required for the anthropic provider."
            )
        if retry_limit < 0:
            raise ProviderConfigurationError("Anthropic retry_limit cannot be negative.")

    @property
    def prompt_version(self) -> str:
        return PROMPT_VERSION

    @property
    def prompt_hash(self) -> str:
        return prompt_hash()

    def extract_claims(
        self, *, transcript: str, turns: list[DialogueTurn]
    ) -> ProviderExtractionResult:
        schema = provider_output_schema()
        client = self._client or self._create_client()
        turn_data = [
            {"turn_index": turn.index, "speaker": turn.speaker.value, "text": turn.text}
            for turn in turns
        ]
        self.last_trace = AnthropicCallTrace()
        final_error: Exception | None = None
        for attempt in range(1, self.retry_limit + 2):
            started = time.perf_counter()
            trace = AnthropicAttemptTrace(attempt=attempt, latency_ms=0)
            try:
                message = client.messages.create(
                    model=self.model,
                    max_tokens=MAX_TOKENS,
                    temperature=TEMPERATURE,
                    system=_SYSTEM,
                    messages=[
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"transcript": transcript, "turns": turn_data},
                                ensure_ascii=False,
                            ),
                        }
                    ],
                    output_config={
                        "format": {
                            "type": "json_schema",
                            "schema": schema,
                        }
                    },
                    timeout=self.timeout_seconds,
                )
                trace.request_id = str(getattr(message, "id", uuid.uuid4()))
                trace.model = str(getattr(message, "model", self.model))
                trace.raw_output = "".join(
                    block.text
                    for block in message.content
                    if getattr(block, "type", None) == "text"
                )
                usage = getattr(message, "usage", None)
                trace.input_tokens = int(getattr(usage, "input_tokens", 0))
                trace.output_tokens = int(getattr(usage, "output_tokens", 0))
                stop_reason = getattr(message, "stop_reason", None)
                if stop_reason in {"max_tokens", "refusal"}:
                    raise ValueError(f"Anthropic response stopped with {stop_reason!r}")
                anthropic_payload = AnthropicExtractionPayload.model_validate_json(
                    trace.raw_output
                )
                payload = anthropic_payload.model_dump(mode="json")
                metadata = ExtractorMetadata(
                    provider="anthropic",
                    model=trace.model,
                    request_id=trace.request_id,
                    schema_version="claim-extraction-v2",
                    attempts=attempt,
                    usage={},
                )
                payload["metadata"] = metadata.model_dump()
                validated = ProviderExtractionResult.model_validate(payload)
                trace.schema_valid = True
                trace.latency_ms = round((time.perf_counter() - started) * 1000)
                self.last_trace.attempts.append(trace)
                validated = validated.model_copy(
                    update={
                        "metadata": validated.metadata.model_copy(
                            update={
                                "attempts": attempt,
                                "usage": self.last_trace.usage,
                            }
                        )
                    }
                )
                self.last_trace.validated_output = validated.model_dump(mode="json")
                return validated
            except (
                json.JSONDecodeError,
                ValidationError,
                AttributeError,
                TypeError,
                ValueError,
            ) as exc:
                final_error = exc
                trace.error_category = "invalid_structured_output"
            except Exception as exc:
                final_error = exc
                trace.error_category = "anthropic_request_error"
                request_id = getattr(exc, "request_id", None)
                trace.request_id = str(request_id) if request_id else None
                status_code = getattr(exc, "status_code", None)
                trace.status_code = int(status_code) if status_code is not None else None
                trace.error_message = str(exc)
                if not exc.__class__.__module__.startswith("anthropic"):
                    trace.latency_ms = round((time.perf_counter() - started) * 1000)
                    self.last_trace.attempts.append(trace)
                    raise
            trace.latency_ms = round((time.perf_counter() - started) * 1000)
            self.last_trace.attempts.append(trace)

        assert final_error is not None
        if self.last_trace.attempts[-1].error_category == "anthropic_request_error":
            raise ProviderOutputError(f"Anthropic request failed: {final_error}") from final_error
        raise ProviderOutputError(
            f"Anthropic returned invalid structured output after "
            f"{len(self.last_trace.attempts)} attempt(s): {final_error}"
        ) from final_error

    def _create_client(self) -> Any:
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderConfigurationError(
                "Install the 'anthropic' dependency to use this provider."
            ) from exc
        return anthropic.Anthropic(
            api_key=self.api_key,
            timeout=self.timeout_seconds,
            max_retries=0,
        )
