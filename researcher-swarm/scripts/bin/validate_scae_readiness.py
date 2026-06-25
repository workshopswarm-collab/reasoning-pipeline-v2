#!/usr/bin/env python3
"""Validate VER-003 SCAE-readiness inputs without writing SCAE rows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from researcher_swarm.verification import (  # noqa: E402
    VerificationError,
    build_scae_readiness_reconciliation,
)


def _load_json(path: Path) -> dict | list:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("classification_matrix", type=Path, help="CLS-003 classification matrix JSON")
    parser.add_argument("--direction-verification", type=Path, required=True, help="VER-001 direction slices or bundle JSON")
    parser.add_argument("--quality-verification", type=Path, required=True, help="VER-002 quality slices or bundle JSON")
    parser.add_argument("--coverage-proof-bundle", type=Path, required=True, help="CLS-005 coverage proof bundle JSON")
    parser.add_argument("--sufficiency-reconciliation", type=Path, required=True, help="VER-004-style sufficiency refs/status inputs JSON")
    parser.add_argument("--escalation-decisions", type=Path, help="Optional CLS-007-style escalation decisions JSON")
    parser.add_argument("--qdt", type=Path, help="Optional question-decomposition JSON")
    parser.add_argument("--output", type=Path, help="Write VER-003 readiness reconciliation JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = build_scae_readiness_reconciliation(
            _load_json(args.classification_matrix),
            _load_json(args.direction_verification),
            _load_json(args.quality_verification),
            qdt=_load_json(args.qdt) if args.qdt else None,
            coverage_proof_bundle=_load_json(args.coverage_proof_bundle),
            sufficiency_reconciliation=_load_json(args.sufficiency_reconciliation),
            escalation_decisions=_load_json(args.escalation_decisions) if args.escalation_decisions else None,
        )
    except (OSError, json.JSONDecodeError, VerificationError) as exc:
        print(f"validate_scae_readiness.py: {exc}", file=sys.stderr)
        return 2

    payload = result.readiness_reconciliation
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    return 0 if result.ready_for_scae else 1


if __name__ == "__main__":
    raise SystemExit(main())
