"""Reduce inspected local results to a public-safe product demonstration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    args = parser.parse_args()
    reports = [
        json.loads(line)
        for line in Path(args.input).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    public = [
        {
            "case": index + 1,
            "summary": report.get("summary", {}),
            "actions": [
                {
                    "route": action.get("route"),
                    "ced_score": action.get("ced_score"),
                    "record_relation": action.get("divergence", {}).get("relation"),
                    "resolved": action.get("resolution", {}).get("resolved"),
                }
                for action in report.get("actions", [])
            ],
        }
        for index, report in enumerate(reports)
    ]
    Path(args.output).write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
