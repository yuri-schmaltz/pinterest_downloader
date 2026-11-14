#!/usr/bin/env python3
"""Validate and summarize the parity matrix; strict mode is a future release gate."""

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "tests/fixtures/parity/requirements.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-complete", action="store_true", help="fail unless every requirement is verified")
    args = parser.parse_args()
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    if matrix.get("schema_version") != 1:
        raise SystemExit("Unsupported matrix version")
    rows = matrix["requirements"]
    seen = set()
    for row in rows:
        for key in ("id", "feature", "scenario", "expected", "status"):
            if not row.get(key):
                raise SystemExit(f"Missing {key}: {row}")
        if row["id"] in seen or row["status"] not in {"planned", "partial", "implemented", "verified"}:
            raise SystemExit(f"Invalid requirement: {row['id']}")
        seen.add(row["id"])
        evidence = row.get("evidence")
        if row["status"] != "planned":
            paths = [evidence] if isinstance(evidence, str) else list(evidence or [])
            if not paths:
                raise SystemExit(f"Evidence missing for {row['id']}")
            for path in paths:
                if not (ROOT / path).is_file():
                    raise SystemExit(f"Evidence file not found for {row['id']}: {path}")
    counts = Counter(row["status"] for row in rows)
    print(
        f"Parity matrix: {len(rows)} requirements; "
        + ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    )
    if args.require_complete and any(row["status"] != "verified" for row in rows):
        print("Full parity is not verified; incomplete requirements remain.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
