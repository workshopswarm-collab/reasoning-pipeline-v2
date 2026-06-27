#!/usr/bin/env python3
"""Researcher Swarm stage entrypoint for validated assignment artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.subagents import (  # noqa: E402
    build_researcher_swarm_runtime_bundle,
    validate_researcher_swarm_runtime_bundle,
)


def _load_json(path: Path | None) -> object | None:
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_records(path: Path | None, key: str) -> list[dict]:
    payload = _load_json(path)
    if payload is None:
        return []
    if isinstance(payload, dict):
        payload = payload.get(key, payload.get("records", payload.get("items", [])))
    if not isinstance(payload, list):
        raise SystemExit(f"{path} must contain a list or {key}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assignments", type=Path, help="Leaf assignment bundle JSON")
    parser.add_argument("--qdt", type=Path, help="Question decomposition JSON for sidecar validation")
    parser.add_argument("--retrieval-packet", type=Path, help="Retrieval packet JSON for admitted-evidence validation")
    parser.add_argument("--sidecars", type=Path, help="Researcher sidecar list/bundle JSON")
    parser.add_argument("--isolation-audits", type=Path, help="Researcher isolation audit list/bundle JSON")
    parser.add_argument("--subagent-results", type=Path, help="Leaf subagent result list/bundle JSON")
    parser.add_argument("--max-concurrent", type=int, default=5)
    parser.add_argument("--true-production", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    assignments = _load_records(args.assignments, "assignments") if args.assignments else []
    bundle = build_researcher_swarm_runtime_bundle(
        assignments,
        qdt=_load_json(args.qdt),
        retrieval_packet=_load_json(args.retrieval_packet),
        sidecars=_load_records(args.sidecars, "sidecars") if args.sidecars else [],
        isolation_audits=_load_records(args.isolation_audits, "isolation_audits") if args.isolation_audits else [],
        subagent_results=_load_records(args.subagent_results, "subagent_results") if args.subagent_results else [],
        true_production_mode=args.true_production,
        max_concurrent=args.max_concurrent,
    )
    bundle["runtime_bundle_validation"] = validate_researcher_swarm_runtime_bundle(bundle).to_dict()
    text = json.dumps(bundle, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
