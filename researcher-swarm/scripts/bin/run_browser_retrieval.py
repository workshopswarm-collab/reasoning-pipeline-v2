#!/usr/bin/env python3
"""Run browser/web-fetch retrieval from live-shaped candidate records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.browser_provider import OPENCLAW_BROWSER_PROVIDER_ID, build_browser_search_provider_diagnostic
from researcher_swarm.retrieval import (  # noqa: E402
    build_live_retrieval_packet_from_candidates,
    dump_retrieval_packet,
    load_json_object,
)


def _load_json_any(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _list_payload(path: Path, field: str) -> list[dict]:
    loaded = _load_json_any(path)
    if isinstance(loaded, dict):
        loaded = loaded.get(field, [])
    if not isinstance(loaded, list):
        raise ValueError(f"{path} must contain a JSON list or object field {field}")
    if not all(isinstance(item, dict) for item in loaded):
        raise ValueError(f"{path} must contain object records")
    return loaded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--available", action="store_true")
    parser.add_argument("--unavailable-reason", default="browser_provider_not_invoked")
    parser.add_argument("--qdt", type=Path, help="question-decomposition/v1 JSON path")
    parser.add_argument("--evidence-packet", type=Path, help="evidence-packet/v2 JSON path")
    parser.add_argument("--amrg-context", type=Path, help="related-live-market-context JSON path")
    parser.add_argument("--candidates", type=Path, help="Browser/web-fetch candidate JSON list")
    parser.add_argument("--search-candidates", type=Path, help="search-candidate-url/v1 raw/provider result JSON list")
    parser.add_argument("--native-candidates", type=Path, help="native-research-candidate-discovery raw JSON list")
    parser.add_argument("--supplemental-candidates", type=Path, help="Supplemental candidate JSON list")
    parser.add_argument("--output", type=Path, help="Write retrieval packet JSON")
    parser.add_argument("--question-decomposition-artifact-id")
    parser.add_argument("--policy-context-ref")
    args = parser.parse_args()
    if args.qdt:
        candidates = _list_payload(args.candidates, "candidates") if args.candidates else []
        supplemental = (
            _list_payload(args.supplemental_candidates, "supplemental_candidates")
            if args.supplemental_candidates
            else []
        )
        search_candidates = (
            _list_payload(args.search_candidates, "search_candidate_urls")
            if args.search_candidates
            else []
        )
        native_candidates = (
            _list_payload(args.native_candidates, "native_research_candidates")
            if args.native_candidates
            else []
        )
        packet = build_live_retrieval_packet_from_candidates(
            load_json_object(args.qdt),
            evidence_packet=load_json_object(args.evidence_packet) if args.evidence_packet else None,
            amrg_context=load_json_object(args.amrg_context) if args.amrg_context else None,
            fetched_candidates=candidates,
            search_candidate_urls=search_candidates,
            native_research_candidates=native_candidates,
            supplemental_candidates=supplemental,
            question_decomposition_artifact_id=args.question_decomposition_artifact_id,
            policy_context_ref=args.policy_context_ref,
        )
        text = dump_retrieval_packet(packet)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0
    payload = build_browser_search_provider_diagnostic(
        availability_status="available" if args.available else "unavailable",
        unavailable_reason=None if args.available else args.unavailable_reason,
    )
    payload["provider_id"] = OPENCLAW_BROWSER_PROVIDER_ID
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
