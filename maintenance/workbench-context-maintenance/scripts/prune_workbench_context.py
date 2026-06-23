#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

WORKBENCH_ROOT = Path("/Users/agent2/.openclaw/workbench")
CONTEXT_ROOT = WORKBENCH_ROOT / "context"
ARCHIVE_ROOT = WORKBENCH_ROOT / "tmp" / "context-archive"

HOT_SET = {
    Path("bootstrap.md"),
    Path("active.md"),
    Path("decisions.md"),
    Path("projects/_index.md"),
    Path("projects/quant-pipeline.md"),
    Path("projects/workbench-context.md"),
    Path("state/README.md"),
}

SUMMARY_README = Path("summaries/README.md")


@dataclass
class FileInfo:
    rel: Path
    bytes: int
    retention: str


def iter_context_files() -> Iterable[Path]:
    for p in sorted(CONTEXT_ROOT.rglob("*")):
        if not p.is_file():
            continue
        if p.name == ".DS_Store":
            continue
        yield p


def classify(rel: Path) -> str:
    if rel in HOT_SET:
        return "hot"
    if rel == SUMMARY_README:
        return "warm"
    if rel.parts[:2] == ("summaries", "generated-difficulty-prompts"):
        return "archive_candidate"
    if rel.parts[:1] == ("summaries",) and rel.name != "README.md":
        return "archive_candidate"
    if rel == Path("inbox.md"):
        return "warm"
    if rel.parts[:1] == ("state",):
        return "warm"
    return "warm"


def gather() -> list[FileInfo]:
    out: list[FileInfo] = []
    for path in iter_context_files():
        rel = path.relative_to(CONTEXT_ROOT)
        out.append(FileInfo(rel=rel, bytes=path.stat().st_size, retention=classify(rel)))
    return out


def print_audit(files: list[FileInfo]) -> None:
    buckets: dict[str, list[FileInfo]] = {}
    for f in files:
        buckets.setdefault(f.retention, []).append(f)
    total = sum(f.bytes for f in files)
    print(f"context_root={CONTEXT_ROOT}")
    print(f"total_files={len(files)} total_bytes={total}")
    for key in ["hot", "warm", "archive_candidate"]:
        group = buckets.get(key, [])
        size = sum(f.bytes for f in group)
        print(f"{key}: files={len(group)} bytes={size}")
        for f in sorted(group, key=lambda x: (-x.bytes, str(x.rel)))[:12]:
            print(f"  {f.bytes:>6}  {f.rel}")


def archive_candidates(files: list[FileInfo], archive_stamp: str) -> dict:
    candidates = [f for f in files if f.retention == "archive_candidate"]
    target_root = ARCHIVE_ROOT / archive_stamp
    manifest = {
        "archive_root": str(target_root),
        "moved": [],
    }
    if not candidates:
        return manifest
    target_root.mkdir(parents=True, exist_ok=True)
    for f in candidates:
        src = CONTEXT_ROOT / f.rel
        dst = target_root / f.rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        manifest["moved"].append({
            "from": str(src),
            "to": str(dst),
            "bytes": f.bytes,
        })
    manifest_path = target_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and prune Workbench context bloat.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("audit", help="Show current hot/warm/archive-candidate context files.")
    apply_p = sub.add_parser("apply", help="Archive known cold context artifacts.")
    apply_p.add_argument("--stamp", default="latest", help="Archive subdirectory name under tmp/context-archive/")

    args = parser.parse_args()
    files = gather()

    if args.cmd == "audit":
        print_audit(files)
        return 0

    manifest = archive_candidates(files, args.stamp)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
