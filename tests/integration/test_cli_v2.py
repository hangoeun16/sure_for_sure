from __future__ import annotations

import json
from pathlib import Path

from backend.cli import main

ROOT = Path(__file__).resolve().parents[2]


def test_cli_runs_public_example_with_complete_product_fields(tmp_path) -> None:
    output = tmp_path / "report.json"
    exit_code = main(
        [
            "analyze",
            "--input",
            str(ROOT / "examples" / "input.example.json"),
            "--provider",
            "stub",
            "--output",
            str(output),
        ]
    )
    report = json.loads(output.read_text())
    assert exit_code == 0
    assert report["claims"][0]["supporting_spans"][0]["text"]
    assert report["record_evidence"][0]["source_path"]
    assert report["divergences"]
    assert report["ced_results"]
    assert report["resolutions"]
    assert report["actions"][0]["recommended_action"]
    assert len(report["source"]["record_sha256"]) == 64
