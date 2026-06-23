#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.sqlite_store import main


if __name__ == "__main__":
    raise SystemExit(main())
