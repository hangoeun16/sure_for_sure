from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
from backend import cli
from pipeline.input_contract import EncounterInput
from pipeline.providers import (
    AnthropicClaimExtractionProvider,
    ProviderConfigurationError,
    ProviderOutputError,
    ProviderSourceGroundingError,
    StubClaimExtractionProvider,
)
from pipeline.providers.anthropic import (
    provider_output_schema,
    validate_anthropic_schema,
)
from pipeline.runner import run_pipeline


def _encounter() -> EncounterInput:
    return EncounterInput(
        id="provider-test",
        metadata={},
        patient_context={},
        encounter_fhir={},
        transcript="PT: I take diltiazem 120 milligrams once daily.",
        note="",
        after_visit_summary="",
        after_visit_summary_provenance={},
    )


def _valid_claims() -> dict:
    return {
        "claims": [
            {
                "medication_name": "Diltiazem",
                "status": "active",
                "dose_value": 120,
                "dose_unit": "milligrams",
                "frequency": "once daily",
                "confidence_cues": [],
                "supporting_quotes": [
                    {"turn_index": 0, "quote": "I take diltiazem 120 milligrams once daily."}
                ],
            }
        ]
    }


def test_stub_output_is_schema_validated_and_spans_round_trip() -> None:
    encounter = _encounter()
    report = run_pipeline(encounter, StubClaimExtractionProvider(_valid_claims()))
    claim = report.claims[0]
    assert claim.medication_name == "diltiazem"
    span = claim.supporting_spans[0]
    assert encounter.transcript[span.start_char : span.end_char] == span.text


def test_malformed_stub_shape_fails_without_fabricated_claims() -> None:
    malformed = _valid_claims()
    del malformed["claims"][0]["medication_name"]
    with pytest.raises(ProviderOutputError, match="schema validation"):
        run_pipeline(_encounter(), StubClaimExtractionProvider(malformed))


def test_inexact_provider_quote_fails_explicitly() -> None:
    malformed = _valid_claims()
    malformed["claims"][0]["supporting_quotes"][0]["quote"] = "I take diltiazem daily."
    with pytest.raises(ProviderSourceGroundingError, match="exact-span"):
        run_pipeline(_encounter(), StubClaimExtractionProvider(malformed))


def test_provider_claim_requires_patient_dialogue_evidence() -> None:
    encounter = _encounter().model_copy(
        update={"transcript": "DR: Continue diltiazem 120 milligrams once daily."}
    )
    output = _valid_claims()
    output["claims"][0]["supporting_quotes"][0]["quote"] = (
        "Continue diltiazem 120 milligrams once daily."
    )
    with pytest.raises(ProviderSourceGroundingError, match="patient-grounded"):
        run_pipeline(encounter, StubClaimExtractionProvider(output))


def test_anthropic_adapter_requires_key_and_model(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SURE_FOR_SURE_ANTHROPIC_MODEL", raising=False)
    with pytest.raises(ProviderConfigurationError, match="ANTHROPIC_API_KEY"):
        AnthropicClaimExtractionProvider()
    with pytest.raises(ProviderConfigurationError, match="MODEL"):
        AnthropicClaimExtractionProvider(api_key="test-key")


def test_anthropic_adapter_rejects_placeholder_key() -> None:
    with pytest.raises(ProviderConfigurationError, match="still a placeholder"):
        AnthropicClaimExtractionProvider(api_key="xxxxx", model="claude-sonnet-4-6")


def _object_schemas(node, path: str = "$"):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield path, node
        for key, value in node.items():
            yield from _object_schemas(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _object_schemas(value, f"{path}[{index}]")


def _additional_properties_values(node):
    if isinstance(node, dict):
        if "additionalProperties" in node:
            yield node["additionalProperties"]
        for value in node.values():
            yield from _additional_properties_values(value)
    elif isinstance(node, list):
        for value in node:
            yield from _additional_properties_values(value)


def test_production_anthropic_schema_is_generated_and_strict_recursively() -> None:
    schema = provider_output_schema()
    objects = list(_object_schemas(schema))
    assert objects
    assert all(isinstance(item.get("properties"), dict) for _, item in objects)
    assert all(item.get("additionalProperties") is False for _, item in objects)
    assert set(_additional_properties_values(schema)) == {False}


def test_anthropic_quote_schema_replaces_free_form_quote_dictionaries() -> None:
    schema = provider_output_schema()
    quote = schema["$defs"]["AnthropicQuote"]
    assert quote["additionalProperties"] is False
    assert set(quote["properties"]) == {"turn_index", "quote"}
    assert set(quote["required"]) == {"turn_index", "quote"}
    assert "ExtractorMetadata" not in schema["$defs"]


def test_anthropic_confidence_cues_use_explicit_grounded_representation() -> None:
    schema = provider_output_schema()
    cue = schema["$defs"]["ProviderConfidenceCue"]
    assert cue["additionalProperties"] is False
    assert set(cue["properties"]) == {"type", "turn_index", "quote"}
    assert set(cue["required"]) == {"type", "turn_index", "quote"}
    cue_types = schema["$defs"]["ConfidenceCueType"]["enum"]
    assert cue_types == [
        "booster",
        "hedge",
        "hesitation",
        "self_justification",
        "authority",
    ]


def test_schema_compatibility_validator_checks_nested_objects() -> None:
    incompatible = {
        "type": "object",
        "properties": {
            "nested": {
                "type": "object",
                "properties": {},
                "additionalProperties": {"type": "string"},
            }
        },
        "additionalProperties": False,
    }
    with pytest.raises(ProviderConfigurationError, match=r"\$\.properties\.nested"):
        validate_anthropic_schema(incompatible)


def test_explicit_anthropic_selection_never_falls_back_to_stub(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("SURE_FOR_SURE_ANTHROPIC_MODEL", "claude-sonnet-4-6")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("stub provider must not be constructed")

    monkeypatch.setattr(cli, "StubClaimExtractionProvider", fail_if_called)
    with pytest.raises(ProviderConfigurationError, match="not configured"):
        cli._provider("anthropic", _encounter())


def test_anthropic_adapter_sends_transcript_and_parses_production_schema() -> None:
    calls = []
    message = SimpleNamespace(
        id="message-valid",
        model="claude-sonnet-4-6",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=json.dumps(_valid_claims()))],
        usage=SimpleNamespace(input_tokens=25, output_tokens=15),
    )

    def create(**kwargs):
        calls.append(kwargs)
        return message

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    provider = AnthropicClaimExtractionProvider(
        api_key="sk-ant-unit-test",
        model="claude-sonnet-4-6",
        client=client,
    )
    report = run_pipeline(_encounter(), provider)
    sent = json.loads(calls[0]["messages"][0]["content"])
    assert sent["transcript"] == _encounter().transcript
    assert sent["turns"][0]["text"] == "I take diltiazem 120 milligrams once daily."
    assert calls[0]["output_config"]["format"]["type"] == "json_schema"
    assert calls[0]["output_config"]["format"]["schema"] == provider_output_schema()
    assert report.claims[0].extractor.provider == "anthropic"
    assert report.claims[0].extractor.usage == {"input_tokens": 25, "output_tokens": 15}


def test_anthropic_adapter_retries_malformed_output_once() -> None:
    responses = [
        SimpleNamespace(
            id="message-invalid",
            model="claude-sonnet-4-6",
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="not-json")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
        ),
        SimpleNamespace(
            id="message-valid",
            model="claude-sonnet-4-6",
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(_valid_claims()))],
            usage=SimpleNamespace(input_tokens=11, output_tokens=12),
        ),
    ]
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return responses[len(calls) - 1]

    provider = AnthropicClaimExtractionProvider(
        api_key="sk-ant-unit-test",
        model="claude-sonnet-4-6",
        client=SimpleNamespace(messages=SimpleNamespace(create=create)),
    )
    result = provider.extract_claims(transcript="PT: hello", turns=[])
    assert len(calls) == 2
    assert result.metadata.attempts == 2
    assert result.metadata.usage == {"input_tokens": 21, "output_tokens": 14}


def test_anthropic_grounding_rejects_fabricated_quote() -> None:
    output = _valid_claims()
    output["claims"][0]["supporting_quotes"][0]["quote"] = "I take diltiazem daily."
    message = SimpleNamespace(
        id="message-inexact",
        model="claude-sonnet-4-6",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=json.dumps(output))],
        usage=SimpleNamespace(input_tokens=20, output_tokens=10),
    )
    provider = AnthropicClaimExtractionProvider(
        api_key="sk-ant-unit-test",
        model="claude-sonnet-4-6",
        client=SimpleNamespace(
            messages=SimpleNamespace(create=lambda **kwargs: message)
        ),
    )
    with pytest.raises(ProviderOutputError, match="exact-span"):
        run_pipeline(_encounter(), provider)


def test_anthropic_adapter_rejects_malformed_json(monkeypatch) -> None:
    message = SimpleNamespace(
        id="message-test",
        model="test-model",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="not-json")],
        usage=SimpleNamespace(input_tokens=10, output_tokens=2),
    )
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: message))
    fake_module = SimpleNamespace(Anthropic=lambda **kwargs: client)
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)
    provider = AnthropicClaimExtractionProvider(api_key="test-key", model="test-model")
    with pytest.raises(ProviderOutputError, match="invalid structured output"):
        provider.extract_claims(transcript="PT: hello", turns=[])
