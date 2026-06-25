#!/usr/bin/env python3
"""CLI wrapper for DEC-001 decision/actionability gate."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.decision_gate import main


if __name__ == "__main__":
    raise SystemExit(main())
