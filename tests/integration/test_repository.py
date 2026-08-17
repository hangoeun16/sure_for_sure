from __future__ import annotations

import json

import pytest
from backend.repository import DuplicateRecordIDError, EncounterRepository, RepositoryError


def _record(identifier: str) -> dict:
    return {
        "id": identifier,
        "metadata": {},
        "patient_context": {},
        "encounter_fhir": {},
        "transcript": "PT: No medication discussion.",
        "note": "",
        "after_visit_summary": "",
        "after_visit_summary_provenance": {},
    }


def test_json_and_jsonl_loading_and_lookup(tmp_path) -> None:
    json_path = tmp_path / "records.json"
    jsonl_path = tmp_path / "records.jsonl"
    records = [_record("one"), _record("two")]
    json_path.write_text(json.dumps(records), encoding="utf-8")
    jsonl_path.write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")
    assert [item.id for item in EncounterRepository(json_path).records()] == ["one", "two"]
    encounter, source = EncounterRepository(jsonl_path).get_by_id("two")
    assert encounter.id == "two"
    assert source.source_record_index == 1
    assert len(source.source_sha256) == 64
    assert len(source.record_sha256) == 64


def test_duplicate_ids_fail_explicitly(tmp_path) -> None:
    path = tmp_path / "duplicate.jsonl"
    path.write_text("\n".join(json.dumps(_record("same")) for _ in range(2)), encoding="utf-8")
    with pytest.raises(DuplicateRecordIDError, match="Duplicate encounter IDs"):
        EncounterRepository(path).raw_records()


def test_malformed_jsonl_reports_line(tmp_path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(_record("ok")) + "\n{", encoding="utf-8")
    with pytest.raises(RepositoryError, match="line 2"):
        EncounterRepository(path).raw_records()
