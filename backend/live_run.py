"""Persisted, inspectable Anthropic runs over organizer-format encounters."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from pipeline.models import EncounterAnalysis
from pipeline.providers.anthropic import (
    MAX_TOKENS,
    TEMPERATURE,
    AnthropicCallTrace,
    AnthropicClaimExtractionProvider,
)
from pipeline.providers.base import ProviderSourceGroundingError
from pipeline.runner import run_pipeline

from backend.repository import EncounterRepository

EXPECTED_ORGANIZER_RECORDS = 25
DEFAULT_ARTIFACTS_ROOT = Path("evaluation/runs/anthropic")
ARTIFACT_FILES = {
    "manifest": "manifest.json",
    "records": "records.jsonl",
    "raw-outputs": "raw_outputs.jsonl",
    "validated-claims": "validated_claims.jsonl",
    "downstream-results": "downstream_results.jsonl",
    "failures": "failures.jsonl",
    "summary": "summary.json",
}


@dataclass(frozen=True)
class LiveRunResult:
    run_directory: Path
    reports: list[EncounterAnalysis]
    summary: dict[str, Any]


def preflight_anthropic_run(
    *,
    input_path: str | Path,
    artifacts_root: str | Path = DEFAULT_ARTIFACTS_ROOT,
) -> dict[str, Any]:
    repository = EncounterRepository(input_path)
    records = repository.records()
    if len(records) != EXPECTED_ORGANIZER_RECORDS:
        raise ValueError(
            "Anthropic batch preflight requires exactly "
            f"{EXPECTED_ORGANIZER_RECORDS} records; found {len(records)}."
        )
    provider = AnthropicClaimExtractionProvider()
    output_root = Path(artifacts_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".preflight-", dir=output_root, delete=True):
        pass
    return {
        "provider": "anthropic",
        "model": provider.model,
        "dataset_file": repository.path.name,
        "dataset_records": len(records),
        "prompt_version": provider.prompt_version,
        "prompt_hash": provider.prompt_hash,
        "output_root": str(output_root),
        "credentials": "configured",
        "live_requests_sent": 0,
        "status": "Ready for live run.",
    }


def run_anthropic_live(
    *,
    repository: EncounterRepository,
    record_indexes: Sequence[int],
    run_kind: str,
    artifacts_root: str | Path = DEFAULT_ARTIFACTS_ROOT,
    provider: AnthropicClaimExtractionProvider | None = None,
) -> LiveRunResult:
    if run_kind not in {"one", "batch"}:
        raise ValueError("run_kind must be 'one' or 'batch'")
    raw_records = repository.raw_records()
    if run_kind == "batch" and len(raw_records) != EXPECTED_ORGANIZER_RECORDS:
        raise ValueError(
            "Live Anthropic batch requires exactly "
            f"{EXPECTED_ORGANIZER_RECORDS} records; found {len(raw_records)}."
        )
    indexes = list(record_indexes)
    if run_kind == "batch" and indexes != list(range(len(raw_records))):
        raise ValueError("Live Anthropic batch must select every dataset record exactly once.")
    if run_kind == "one" and len(indexes) != 1:
        raise ValueError("One-record live run must select exactly one record.")

    extractor = provider or AnthropicClaimExtractionProvider()
    assert extractor.model is not None
    assert extractor.api_key is not None
    model = extractor.model
    api_key = extractor.api_key
    root = Path(artifacts_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    run_id = _run_id(model, extractor.prompt_version)
    run_directory = root / run_id
    run_directory.mkdir(parents=False, exist_ok=False)
    for filename in ARTIFACT_FILES.values():
        if filename.endswith(".jsonl"):
            (run_directory / filename).write_text("", encoding="utf-8")

    timestamp = datetime.now(UTC).isoformat()
    manifest = {
        "run_id": run_id,
        "timestamp": timestamp,
        "run_kind": run_kind,
        "provider": "anthropic",
        "model": model,
        "prompt_version": extractor.prompt_version,
        "prompt_hash": extractor.prompt_hash,
        "dataset_identifier": repository.path.stem,
        "dataset_file": repository.path.name,
        "dataset_sha256": hashlib.sha256(repository.path.read_bytes()).hexdigest(),
        "dataset_record_count": len(raw_records),
        "records_selected": len(indexes),
        "pipeline_version": _pipeline_version(),
        "git_commit": _repository_commit(),
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "timeout_seconds": extractor.timeout_seconds,
        "retry_limit": extractor.retry_limit,
        "schema_version": "claim-extraction-v2",
    }
    _write_json(run_directory / ARTIFACT_FILES["manifest"], manifest, api_key)

    reports: list[EncounterAnalysis] = []
    record_results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    schema_valid_responses = 0
    grounding_valid_responses = 0
    total_claims = 0
    error_counts: Counter[str] = Counter()

    for index in indexes:
        raw = raw_records[index]
        record_id = str(raw.get("id", ""))
        started = datetime.now(UTC)
        report: EncounterAnalysis | None = None
        error: Exception | None = None
        try:
            encounter, source = repository.get_by_index(index)
            report = run_pipeline(encounter, extractor, source=source)
            reports.append(report)
            grounding_valid_responses += 1
            total_claims += len(report.claims)
        except Exception as exc:  # A batch records and continues after per-record failures.
            error = exc

        trace = extractor.last_trace
        if trace.validated_output is not None:
            schema_valid_responses += 1
        _append_raw_attempts(run_directory, record_id, index, trace, api_key)
        if trace.validated_output is not None:
            _append_jsonl(
                run_directory / ARTIFACT_FILES["validated-claims"],
                {
                    "record_id": record_id,
                    "record_index": index,
                    "provider": "anthropic",
                    "model": model,
                    "prompt_version": extractor.prompt_version,
                    "schema_valid": True,
                    "grounding_valid": report is not None,
                    "validated_structured_output": trace.validated_output,
                },
                api_key,
            )
        if report is not None:
            _append_jsonl(
                run_directory / ARTIFACT_FILES["downstream-results"],
                {
                    "record_id": record_id,
                    "record_index": index,
                    "pipeline_output": report.model_dump(mode="json"),
                },
                api_key,
            )

        elapsed_ms = round((datetime.now(UTC) - started).total_seconds() * 1000)
        operational = {
            "record_id": record_id,
            "record_index": index,
            "provider": "anthropic",
            "model": model,
            "prompt_version": extractor.prompt_version,
            "validation_status": "valid" if report is not None else "failed",
            "schema_valid": trace.validated_output is not None,
            "grounding_valid": report is not None,
            "pipeline_succeeded": report is not None,
            "number_of_extracted_claims": len(report.claims) if report is not None else None,
            "latency_ms": elapsed_ms,
            "provider_latency_ms": trace.latency_ms,
            "input_tokens": trace.usage["input_tokens"],
            "output_tokens": trace.usage["output_tokens"],
            "request_count": len(trace.attempts),
            "retry_count": max(0, len(trace.attempts) - 1),
            "error_category": None,
        }
        if error is not None:
            category = _error_category(error, trace)
            final_attempt = trace.attempts[-1] if trace.attempts else None
            operational["error_category"] = category
            error_counts[category] += 1
            failure = {
                "record_id": record_id,
                "record_index": index,
                "error_category": category,
                "error": str(error),
                "schema_valid": trace.validated_output is not None,
                "grounding_valid": False,
                "request_count": len(trace.attempts),
                "retry_count": max(0, len(trace.attempts) - 1),
                "request_id": final_attempt.request_id if final_attempt else None,
                "status_code": final_attempt.status_code if final_attempt else None,
            }
            failures.append(failure)
            _append_jsonl(
                run_directory / ARTIFACT_FILES["failures"], failure, api_key
            )
        record_results.append(operational)
        _append_jsonl(
            run_directory / ARTIFACT_FILES["records"], operational, api_key
        )

    summary = {
        "run_id": run_id,
        "run_kind": run_kind,
        "provider": "anthropic",
        "model": model,
        "prompt_version": extractor.prompt_version,
        "records_attempted": len(indexes),
        "successful_api_responses": sum(item["schema_valid"] for item in record_results),
        "schema_valid_responses": schema_valid_responses,
        "grounding_valid_responses": grounding_valid_responses,
        "pipeline_successes": len(reports),
        "failed_records": len(failures),
        "total_extracted_claims": total_claims,
        "request_count": sum(item["request_count"] for item in record_results),
        "retry_count": sum(item["retry_count"] for item in record_results),
        "input_tokens": sum(item["input_tokens"] for item in record_results),
        "output_tokens": sum(item["output_tokens"] for item in record_results),
        "latency_ms": sum(item["latency_ms"] for item in record_results),
        "provider_latency_ms": sum(item["provider_latency_ms"] for item in record_results),
        "error_counts": dict(error_counts),
        "artifact_directory": str(run_directory),
    }
    _write_json(run_directory / ARTIFACT_FILES["summary"], summary, api_key)
    (root / f"LATEST_{run_kind.upper()}").write_text(run_id + "\n", encoding="utf-8")
    return LiveRunResult(run_directory=run_directory, reports=reports, summary=summary)


def inspect_latest_run(
    *,
    artifacts_root: str | Path,
    run_kind: str,
    artifact: str,
) -> str:
    if run_kind not in {"one", "batch"}:
        raise ValueError("latest run kind must be 'one' or 'batch'")
    if artifact not in ARTIFACT_FILES:
        raise ValueError(f"Unknown artifact: {artifact}")
    root = Path(artifacts_root).expanduser().resolve()
    pointer = root / f"LATEST_{run_kind.upper()}"
    if not pointer.is_file():
        raise ValueError(f"No latest {run_kind} run pointer exists under {root}")
    run_id = pointer.read_text(encoding="utf-8").strip()
    if not run_id or Path(run_id).name != run_id:
        raise ValueError("Latest run pointer is invalid")
    target = root / run_id / ARTIFACT_FILES[artifact]
    if not target.is_file():
        raise ValueError(f"Run artifact does not exist: {target}")
    return target.read_text(encoding="utf-8")


def _append_raw_attempts(
    run_directory: Path,
    record_id: str,
    record_index: int,
    trace: AnthropicCallTrace,
    api_key: str,
) -> None:
    for attempt in trace.attempts:
        _append_jsonl(
            run_directory / ARTIFACT_FILES["raw-outputs"],
            {
                "record_id": record_id,
                "record_index": record_index,
                "attempt": attempt.attempt,
                "request_id": attempt.request_id,
                "model": attempt.model,
                "raw_model_output": attempt.raw_output,
                "schema_valid": attempt.schema_valid,
                "input_tokens": attempt.input_tokens,
                "output_tokens": attempt.output_tokens,
                "latency_ms": attempt.latency_ms,
                "error_category": attempt.error_category,
                "status_code": attempt.status_code,
                "error_message": attempt.error_message,
            },
            api_key,
        )


def _error_category(error: Exception, trace: AnthropicCallTrace) -> str:
    if isinstance(error, ProviderSourceGroundingError):
        return "source_grounding_error"
    if trace.attempts and trace.attempts[-1].error_category:
        return str(trace.attempts[-1].error_category)
    return type(error).__name__


def _run_id(model: str, prompt_version: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    safe_model = re.sub(r"[^a-zA-Z0-9._-]+", "-", model).strip("-")
    safe_prompt = re.sub(r"[^a-zA-Z0-9._-]+", "-", prompt_version).strip("-")
    return f"{stamp}_{safe_model}_{safe_prompt}"


def _pipeline_version() -> str:
    try:
        return version("sure-for-sure")
    except PackageNotFoundError:
        return "0.1.0"


def _repository_commit() -> str | None:
    repository_root = Path(__file__).resolve().parents[1]
    if not (repository_root / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _write_json(path: Path, value: Any, api_key: str) -> None:
    safe = _redact(value, api_key)
    path.write_text(json.dumps(safe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, value: Any, api_key: str) -> None:
    safe = _redact(value, api_key)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe, ensure_ascii=False) + "\n")


def _redact(value: Any, api_key: str) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact(item, api_key) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, api_key) for item in value]
    if isinstance(value, tuple):
        return [_redact(item, api_key) for item in value]
    if isinstance(value, str) and api_key:
        return value.replace(api_key, "[REDACTED]")
    return value
