"""Validate organizer-compatible JSON or JSONL without running analysis."""

from __future__ import annotations

import argparse

from backend.repository import EncounterRepository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    args = parser.parse_args()
    records = EncounterRepository(args.input).records()
    print(f"Validated {len(records)} encounter record(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
