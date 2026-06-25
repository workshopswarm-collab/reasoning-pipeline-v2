#!/usr/bin/env python3
"""Validate question-decomposition/v1 JSON artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ads_decomposer.qdt import (  # noqa: E402
    load_question_decomposition,
    validate_question_decomposition,
)
from predquant.ads_handoff import canonical_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a question-decomposition/v1 artifact.")
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--candidate",
        action="store_true",
        help="Validate a candidate before final selection audit fields are written.",
    )
    args = parser.parse_args()

    artifact = load_question_decomposition(args.path)
    result = validate_question_decomposition(artifact, require_selected=not args.candidate)
    print(canonical_json(result.to_dict()))
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
