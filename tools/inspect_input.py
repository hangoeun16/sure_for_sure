"""Report input shape without reproducing transcript or patient content."""

from __future__ import annotations

import argparse
from collections import Counter

from backend.repository import EncounterRepository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    args = parser.parse_args()
    records = EncounterRepository(args.input).raw_records()
    resource_types = Counter(
        key
        for record in records
        for key in record.get("encounter_fhir", {}).get("related_resources", {})
    )
    print(
        {
            "records": len(records),
            "resource_types": dict(sorted(resource_types.items())),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
