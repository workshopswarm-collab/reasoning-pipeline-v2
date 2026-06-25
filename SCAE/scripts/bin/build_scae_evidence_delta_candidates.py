#!/usr/bin/env python3
"""Build SCAE-003/SCAE-004 evidence delta candidate slices from JSON artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_ROOT))

from scae.evidence import ScaeEvidenceDeltaError, build_evidence_delta_candidate_bundle  # noqa: E402


def _load_payload(path: str | None) -> dict:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.load(sys.stdin)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build guarded SCAE candidate log-odds update slices.")
    parser.add_argument("--input", help="JSON input path. Defaults to stdin.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args()

    try:
        payload = _load_payload(args.input)
        bundle = build_evidence_delta_candidate_bundle(
            payload.get("classification_matrix") or payload.get("classification_slices"),
            direction_verification_slices=payload.get("direction_verification_slices")
            or payload.get("direction_verification_bundle"),
            quality_verification_slices=payload.get("quality_verification_slices")
            or payload.get("quality_verification_bundle"),
            market_assimilation_contexts=payload.get("market_assimilation_contexts"),
            policy=payload.get("policy"),
        )
    except (json.JSONDecodeError, ScaeEvidenceDeltaError, TypeError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2

    json.dump(bundle, sys.stdout, sort_keys=True, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
