#!/usr/bin/env python3
"""CLI wrapper for SYN-001 qualitative synthesis annotation."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.synthesis_annotation import main


if __name__ == "__main__":
    raise SystemExit(main())
