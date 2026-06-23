#!/usr/bin/env python3
"""Compatibility shim for the launchd entrypoint now housed in bin/."""

import runpy
from pathlib import Path


if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "bin" / "check_pipeline_health.py"
    runpy.run_path(str(target), run_name="__main__")
