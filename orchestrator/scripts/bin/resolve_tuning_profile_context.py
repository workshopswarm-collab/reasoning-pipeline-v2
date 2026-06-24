#!/usr/bin/env python3
"""CLI wrapper for ADS tuning profile context resolution."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.tuning_profile import main


if __name__ == "__main__":
    raise SystemExit(main())
