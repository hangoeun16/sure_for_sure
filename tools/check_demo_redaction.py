"""Fail when public demo JSON contains source transcripts or direct identifiers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

FORBIDDEN_KEYS = {
    "transcript",
    "note",
    "after_visit_summary",
    "patient_id",
    "source_sha256",
    "record_sha256",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
    found = _find_forbidden(payload)
    if found:
        raise SystemExit(f"Public demo contains forbidden fields: {sorted(found)}")
    print("Demo redaction check passed.")
    return 0


def _find_forbidden(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value if key in FORBIDDEN_KEYS} | set().union(
            *(_find_forbidden(item) for item in value.values()), set()
        )
    if isinstance(value, list):
        return set().union(*(_find_forbidden(item) for item in value), set())
    return set()


if __name__ == "__main__":
    raise SystemExit(main())
