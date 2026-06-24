#!/usr/bin/env python3
"""CLI wrapper for ADS AMRG related live-market context materialization."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.amrg import main


if __name__ == "__main__":
    raise SystemExit(main())
