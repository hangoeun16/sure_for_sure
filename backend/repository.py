"""JSON/JSONL repository and immutable source identity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pipeline.input_contract import EncounterInput
from pipeline.models import SourceProvenance


class RepositoryError(ValueError):
    pass


class DuplicateRecordIDError(RepositoryError):
    pass


def canonical_record_hash(record: dict[str, Any]) -> str:
    material = json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(material).hexdigest()


class EncounterRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    def records(self) -> list[EncounterInput]:
        return [EncounterInput.model_validate(record) for record in self.raw_records()]

    def raw_records(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            raise RepositoryError(f"Encounter input does not exist: {self.path}")
        try:
            if self.path.suffix.lower() == ".jsonl":
                values = []
                for line_number, line in enumerate(
                    self.path.read_text(encoding="utf-8").splitlines(), start=1
                ):
                    if not line.strip():
                        continue
                    try:
                        values.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        raise RepositoryError(
                            f"Invalid JSONL at line {line_number}: {exc.msg}"
                        ) from exc
            else:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                values = payload if isinstance(payload, list) else [payload]
            if not all(isinstance(value, dict) for value in values):
                raise RepositoryError("Input must contain JSON objects.")
            identifiers = [str(value.get("id", "")) for value in values]
            duplicates = sorted(
                identifier
                for identifier in set(identifiers)
                if identifier and identifiers.count(identifier) > 1
            )
            if duplicates:
                raise DuplicateRecordIDError(f"Duplicate encounter IDs: {', '.join(duplicates)}")
            return values
        except json.JSONDecodeError as exc:
            raise RepositoryError(f"Invalid encounter input: {exc}") from exc

    def get_by_index(self, index: int) -> tuple[EncounterInput, SourceProvenance]:
        raw = self.raw_records()
        try:
            record = raw[index]
        except IndexError as exc:
            raise RepositoryError(f"Record index is out of range: {index}") from exc
        return EncounterInput.model_validate(record), self.source_for(index, record)

    def get_by_id(self, record_id: str) -> tuple[EncounterInput, SourceProvenance]:
        for index, record in enumerate(self.raw_records()):
            if str(record.get("id")) == record_id:
                return EncounterInput.model_validate(record), self.source_for(index, record)
        raise RepositoryError(f"Unknown encounter ID: {record_id}")

    def source_for(self, index: int, record: dict[str, Any]) -> SourceProvenance:
        return SourceProvenance(
            source_dataset=self.path.stem,
            source_file=self.path.name,
            source_record_id=str(record.get("id", "")),
            source_record_index=index,
            source_sha256=hashlib.sha256(self.path.read_bytes()).hexdigest(),
            record_sha256=canonical_record_hash(record),
        )

    def listing(self) -> list[dict[str, Any]]:
        return [
            {
                "id": str(record.get("id", "")),
                "index": index,
                "title": str(record.get("metadata", {}).get("visit_title", "Encounter")),
                "date": record.get("metadata", {}).get("date"),
                "visit_type": record.get("metadata", {}).get("visit_type"),
            }
            for index, record in enumerate(self.raw_records())
        ]
