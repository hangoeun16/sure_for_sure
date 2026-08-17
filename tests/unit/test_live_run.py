from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from backend.live_run import preflight_anthropic_run, run_anthropic_live
from backend.repository import EncounterRepository
from pipeline.providers import AnthropicClaimExtractionProvider


class FakeAnthropicRequestError(Exception):
    __module__ = "anthropic"

    def __init__(self) -> None:
        super().__init__("400 invalid_request_error: incompatible schema")
        self.request_id = "req_schema_test"
        self.status_code = 400


def _record(
    identifier: str = "live-test",
    transcript: str = "PT: I take diltiazem 120 milligrams once daily.",
) -> dict:
    return {
        "id": identifier,
        "metadata": {},
        "patient_context": {},
        "encounter_fhir": {},
        "transcript": transcript,
        "note": "",
        "after_visit_summary": "",
        "after_visit_summary_provenance": {},
    }


def _provider(
    api_key: str,
    medication_name: str = "diltiazem",
    *,
    confidence_cues: list[dict] | None = None,
    supporting_quote: str = "I take diltiazem 120 milligrams once daily.",
    supporting_turn_index: int = 0,
):
    output = {
        "claims": [
            {
                "medication_name": medication_name,
                "status": "active",
                "dose_value": 120,
                "dose_unit": "milligrams",
                "frequency": "once daily",
                "confidence_cues": confidence_cues or [],
                "supporting_quotes": [
                    {
                        "turn_index": supporting_turn_index,
                        "quote": supporting_quote,
                    }
                ],
            }
        ]
    }
    message = SimpleNamespace(
        id="message-live-test",
        model="claude-sonnet-4-6",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=json.dumps(output))],
        usage=SimpleNamespace(input_tokens=20, output_tokens=10),
    )
    client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kwargs: message)
    )
    return AnthropicClaimExtractionProvider(
        api_key=api_key,
        model="claude-sonnet-4-6",
        client=client,
    )


def test_preflight_validates_25_records_without_sending_requests(
    tmp_path: Path, monkeypatch
) -> None:
    dataset = tmp_path / "synthetic-ambient-fhir-25.json"
    dataset.write_text(
        json.dumps([_record(f"preflight-{index}") for index in range(25)]),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-preflight-test")
    monkeypatch.setenv("SURE_FOR_SURE_ANTHROPIC_MODEL", "claude-sonnet-4-6")
    result = preflight_anthropic_run(
        input_path=dataset,
        artifacts_root=tmp_path / "runs",
    )
    assert result["dataset_records"] == 25
    assert result["live_requests_sent"] == 0
    assert result["credentials"] == "configured"


def test_live_artifacts_redact_key_and_separate_output_layers(tmp_path: Path) -> None:
    api_key = "sk-ant-super-secret-unit-test"
    dataset = tmp_path / "one.json"
    dataset.write_text(json.dumps(_record()), encoding="utf-8")
    result = run_anthropic_live(
        repository=EncounterRepository(dataset),
        record_indexes=[0],
        run_kind="one",
        artifacts_root=tmp_path / "runs",
        provider=_provider(api_key, medication_name=f"diltiazem {api_key}"),
    )

    artifact_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in result.run_directory.iterdir()
        if path.is_file()
    )
    assert api_key not in artifact_text
    assert "[REDACTED]" in artifact_text

    raw = json.loads((result.run_directory / "raw_outputs.jsonl").read_text())
    validated = json.loads(
        (result.run_directory / "validated_claims.jsonl").read_text()
    )
    downstream = json.loads(
        (result.run_directory / "downstream_results.jsonl").read_text()
    )
    assert "raw_model_output" in raw
    assert "validated_structured_output" not in raw
    assert "validated_structured_output" in validated
    assert "raw_model_output" not in validated
    assert "pipeline_output" in downstream
    assert result.summary["schema_valid_responses"] == 1
    assert result.summary["pipeline_successes"] == 1


def test_live_artifact_records_cue_warning_without_failing_claim(tmp_path: Path) -> None:
    dataset = tmp_path / "one.json"
    dataset.write_text(
        json.dumps(
            _record(
                transcript=(
                    "PT: She never misses.\n"
                    "PT: I take diltiazem 120 milligrams once daily."
                )
            )
        ),
        encoding="utf-8",
    )
    provider = _provider(
        "sk-ant-cue-warning-test",
        confidence_cues=[
            {"type": "booster", "turn_index": 0, "quote": "She never misses."}
        ],
        supporting_turn_index=1,
    )

    result = run_anthropic_live(
        repository=EncounterRepository(dataset),
        record_indexes=[0],
        run_kind="one",
        artifacts_root=tmp_path / "runs",
        provider=provider,
    )

    downstream = json.loads(
        (result.run_directory / "downstream_results.jsonl").read_text()
    )
    confidence = downstream["pipeline_output"]["claims"][0]["confidence"]
    assert result.summary["pipeline_successes"] == 1
    assert result.summary["failed_records"] == 0
    assert confidence["level"] == "neutral"
    assert confidence["cues"] == []
    assert confidence["validation_warnings"][0]["code"] == (
        "cue_outside_patient_support"
    )
    assert (result.run_directory / "failures.jsonl").read_text() == ""


def test_live_artifact_reserves_source_grounding_error_for_claim_support(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "one.json"
    dataset.write_text(json.dumps(_record()), encoding="utf-8")
    provider = _provider(
        "sk-ant-source-grounding-test",
        supporting_quote="I take invented diltiazem.",
    )

    result = run_anthropic_live(
        repository=EncounterRepository(dataset),
        record_indexes=[0],
        run_kind="one",
        artifacts_root=tmp_path / "runs",
        provider=provider,
    )

    failure = json.loads((result.run_directory / "failures.jsonl").read_text())
    assert result.summary["pipeline_successes"] == 0
    assert failure["error_category"] == "source_grounding_error"


def test_request_error_artifact_preserves_safe_anthropic_diagnostics(tmp_path: Path) -> None:
    api_key = "sk-ant-request-error-test"
    dataset = tmp_path / "one.json"
    dataset.write_text(json.dumps(_record()), encoding="utf-8")

    def fail(**kwargs):
        raise FakeAnthropicRequestError()

    provider = AnthropicClaimExtractionProvider(
        api_key=api_key,
        model="claude-sonnet-4-6",
        client=SimpleNamespace(messages=SimpleNamespace(create=fail)),
    )
    result = run_anthropic_live(
        repository=EncounterRepository(dataset),
        record_indexes=[0],
        run_kind="one",
        artifacts_root=tmp_path / "runs",
        provider=provider,
    )
    failure = json.loads((result.run_directory / "failures.jsonl").read_text())
    assert failure["error_category"] == "anthropic_request_error"
    assert failure["status_code"] == 400
    assert failure["request_id"] == "req_schema_test"
    assert failure["request_count"] == 2
    assert failure["retry_count"] == 1
    assert api_key not in json.dumps(failure)
