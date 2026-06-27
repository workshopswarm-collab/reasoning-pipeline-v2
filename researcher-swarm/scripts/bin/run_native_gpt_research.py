#!/usr/bin/env python3
"""Record a RET-010 native research attempt or unavailable diagnostic."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.native_research import (
    build_native_research_candidate_discovery,
    build_native_research_transport_diagnostic,
)
from researcher_swarm.retrieval import build_retrieval_query_contexts, load_json_object


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", default="unavailable")
    parser.add_argument("--unavailable-reason", default="native_research_not_invoked")
    parser.add_argument("--qdt", type=Path, help="question-decomposition/v1 JSON path")
    parser.add_argument("--evidence-packet", type=Path, help="Optional evidence-packet/v2 JSON path")
    parser.add_argument("--candidate-output", type=Path, help="Native GPT candidate JSON list or {native_research_candidates: [...]}")
    parser.add_argument("--output", type=Path, help="Write candidate-discovery bundle JSON")
    args = parser.parse_args()
    if args.qdt and args.candidate_output:
        loaded = json.loads(args.candidate_output.read_text(encoding="utf-8"))
        candidates = loaded.get("native_research_candidates", loaded) if isinstance(loaded, dict) else loaded
        if not isinstance(candidates, list):
            raise SystemExit("--candidate-output must contain a list or native_research_candidates list")
        qdt = load_json_object(args.qdt)
        contexts = {
            str(context["leaf_id"]): context
            for context in build_retrieval_query_contexts(
                qdt,
                evidence_packet=load_json_object(args.evidence_packet) if args.evidence_packet else None,
            )
        }
        discoveries = []
        for raw in candidates:
            if not isinstance(raw, dict):
                raise SystemExit("native research candidates must be objects")
            leaf_id = str(raw.get("leaf_id") or raw.get("related_leaf_id") or "")
            context = contexts.get(leaf_id)
            if not context:
                raise SystemExit(f"candidate leaf_id is not dispatchable: {leaf_id}")
            variants = context.get("query_variants") or []
            if not variants:
                raise SystemExit(f"candidate leaf_id has no query variants: {leaf_id}")
            variant = next(
                (
                    item
                    for item in variants
                    if isinstance(item, dict) and item.get("query_variant_id") == raw.get("query_variant_id")
                ),
                variants[0],
            )
            candidate_urls = raw.get("candidate_urls") if isinstance(raw.get("candidate_urls"), list) else [raw]
            discoveries.append(
                build_native_research_candidate_discovery(
                    context,
                    variant,
                    candidate_urls,
                    attempt_ref=raw.get("native_research_attempt_ref") or raw.get("attempt_ref"),
                    resolved_model_id=str(raw.get("resolved_model_id") or "gpt-5.5-high"),
                )
            )
        payload = {
            "artifact_type": "native_research_candidate_discovery_bundle",
            "schema_version": "native-research-candidate-discovery-bundle/v1",
            "native_research_candidate_discoveries": discoveries,
        }
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0
    payload = build_native_research_transport_diagnostic(
        availability_status=args.status,
        unavailable_reason=args.unavailable_reason,
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
