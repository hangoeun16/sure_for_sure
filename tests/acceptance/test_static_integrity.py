from __future__ import annotations

import ast
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_ROOTS = (REPO_ROOT / "pipeline", REPO_ROOT / "backend")
DATASET_PATH = REPO_ROOT / "synthetic-ambient-fhir-25" / "synthetic-ambient-fhir-25.jsonl"


def _production_files() -> list[Path]:
    return [path for root in PRODUCTION_ROOTS for path in root.rglob("*.py")]


def test_production_contains_no_organizer_record_ids() -> None:
    records = [json.loads(line) for line in DATASET_PATH.read_text().splitlines()]
    organizer_ids = {
        value
        for record in records
        for value in (
            str(record["id"]),
            str(record["metadata"]["patient_id"]),
            str(record["metadata"]["encounter_id"]),
        )
    }
    production = "\n".join(path.read_text() for path in _production_files())
    assert not sorted(identifier for identifier in organizer_ids if identifier in production)


def test_production_contains_no_copied_full_organizer_utterances() -> None:
    records = [json.loads(line) for line in DATASET_PATH.read_text().splitlines()]
    long_utterances = {
        line.strip()
        for record in records
        for line in str(record.get("transcript", "")).splitlines()
        if len(line.strip()) >= 70
    }
    production = "\n".join(path.read_text() for path in _production_files())
    assert not sorted(line for line in long_utterances if line in production)


def test_production_has_no_record_specific_control_flow() -> None:
    violations: list[str] = []
    record_field = re.compile(r"(?:record|source)_?(?:id|index)$")
    for path in _production_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                for left, right in zip(operands, operands[1:], strict=False):
                    for candidate, constant in ((left, right), (right, left)):
                        name = (
                            candidate.attr
                            if isinstance(candidate, ast.Attribute)
                            else candidate.id
                            if isinstance(candidate, ast.Name)
                            else ""
                        )
                        if record_field.search(name) and isinstance(constant, ast.Constant):
                            violations.append(f"{path}:{node.lineno}")
    assert violations == []


def test_extraction_has_no_production_medication_inventory() -> None:
    extraction_files = [
        REPO_ROOT / "pipeline" / "stage_02_extract_claims.py",
        REPO_ROOT / "pipeline" / "providers" / "anthropic.py",
    ]
    production = "\n".join(path.read_text() for path in extraction_files)
    assert "CANONICAL_MEDICATIONS" not in production
    assert "CONTEXTUAL_MEDICATION_RE" not in production


def test_only_one_product_runtime_exists() -> None:
    assert not (REPO_ROOT / "src" / "sure_for_sure").exists()
