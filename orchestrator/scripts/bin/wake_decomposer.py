#!/usr/bin/env python3
"""Build an Orchestrator-owned wakeup envelope for ADS Decomposer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_handoff import canonical_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-contract-ref", required=True)
    parser.add_argument("--evidence-packet-ref", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    envelope = {
        "schema_version": "ads-agent-wakeup-envelope/v1",
        "target_runtime_owner": "ADS Decomposer",
        "target_stage": "question_decomposition",
        "handoff_refs": {
            "ads_case_contract_ref": args.case_contract_ref,
            "evidence_packet_ref": args.evidence_packet_ref,
        },
        "orchestrator_authority": "handoff_only",
    }
    text = canonical_json(envelope) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
