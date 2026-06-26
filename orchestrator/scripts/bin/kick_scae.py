#!/usr/bin/env python3
"""Build an Orchestrator-owned post-research SCAE invocation envelope."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_handoff import canonical_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scae-readiness-ref", required=True)
    parser.add_argument("--sufficiency-reconciliation-ref", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    envelope = {
        "schema_version": "ads-agent-wakeup-envelope/v1",
        "target_runtime_owner": "SCAE",
        "target_stage": "scae_ledger",
        "handoff_refs": {
            "scae_readiness_ref": args.scae_readiness_ref,
            "sufficiency_reconciliation_ref": args.sufficiency_reconciliation_ref,
        },
        "orchestrator_authority": "handoff_only_no_probability",
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
