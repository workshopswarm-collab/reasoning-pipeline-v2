#!/usr/bin/env python3
"""Build a RET-001 retrieval-packet/v1 artifact from a QDT artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from researcher_swarm.retrieval import (  # noqa: E402
    RetrievalPacketError,
    build_retrieval_packet,
    build_retrieval_packet_manifest,
    dump_retrieval_packet,
    load_json_object,
    validate_retrieval_packet,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("qdt", type=Path, help="Path to question-decomposition.json")
    parser.add_argument("--evidence-packet", type=Path, help="Optional evidence-packet/v2 JSON path")
    parser.add_argument("--amrg-context", type=Path, help="Optional related-live-market-context JSON path")
    parser.add_argument("--output", type=Path, help="Write retrieval packet JSON to this path")
    parser.add_argument("--manifest-output", type=Path, help="Write artifact manifest JSON for --output")
    parser.add_argument("--question-decomposition-artifact-id", help="Artifact manifest ID for the QDT")
    parser.add_argument("--policy-context-ref", help="Effective tuning/profile context artifact ref")
    parser.add_argument("--forecast-timestamp", help="Forecast timestamp override")
    parser.add_argument("--source-cutoff-timestamp", help="Source cutoff timestamp override")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        qdt = load_json_object(args.qdt)
        evidence_packet = load_json_object(args.evidence_packet) if args.evidence_packet else None
        amrg_context = load_json_object(args.amrg_context) if args.amrg_context else None
        packet = build_retrieval_packet(
            qdt,
            evidence_packet=evidence_packet,
            amrg_context=amrg_context,
            question_decomposition_artifact_id=args.question_decomposition_artifact_id,
            policy_context_ref=args.policy_context_ref,
            forecast_timestamp=args.forecast_timestamp,
            source_cutoff_timestamp=args.source_cutoff_timestamp,
        )
        result = validate_retrieval_packet(packet)
        if not result.valid:
            print(json.dumps(result.to_dict(), sort_keys=True), file=sys.stderr)
            return 1
        serialized = dump_retrieval_packet(packet)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(serialized, encoding="utf-8")
            if args.manifest_output:
                manifest = build_retrieval_packet_manifest(packet, path=args.output)
                args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
                args.manifest_output.write_text(
                    json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                    encoding="utf-8",
                )
            print(json.dumps(result.to_dict(), sort_keys=True))
        else:
            print(serialized, end="")
        return 0
    except (OSError, json.JSONDecodeError, RetrievalPacketError) as exc:
        print(f"build_retrieval_packet.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
