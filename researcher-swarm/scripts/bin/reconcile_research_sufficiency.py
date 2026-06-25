#!/usr/bin/env python3
"""Build VER-004 research sufficiency reconciliation from fixture artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.verification import build_research_sufficiency_reconciliation  # noqa: E402


def _read_json(path: str | None) -> dict | list | None:
    if path is None:
        return None
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qdt", required=True, help="Path to question-decomposition.json")
    parser.add_argument("--retrieval-packet", required=True, help="Path to retrieval-packet.json")
    parser.add_argument("--coverage-proof-bundle", required=True, help="Path to CLS-005 coverage proof bundle")
    parser.add_argument("--classification-matrix", help="Path to CLS-003 classification matrix")
    parser.add_argument("--escalation-decisions", help="Path to CLS-007 escalation decisions")
    parser.add_argument("--output", help="Optional output path; defaults to stdout")
    args = parser.parse_args(argv)

    result = build_research_sufficiency_reconciliation(
        qdt=_read_json(args.qdt),
        retrieval_packet=_read_json(args.retrieval_packet),
        coverage_proof_bundle=_read_json(args.coverage_proof_bundle),
        classification_matrix=_read_json(args.classification_matrix),
        escalation_decisions=_read_json(args.escalation_decisions),
    )
    text = json.dumps(result.reconciliation_bundle, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
