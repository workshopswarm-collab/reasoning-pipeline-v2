#!/usr/bin/env python3
"""Phase 0 helpers for maintenance baseline capture and test cleanup."""
from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

MAINTENANCE_ROOT = Path(__file__).resolve().parents[1]
if str(MAINTENANCE_ROOT) not in sys.path:
    sys.path.insert(0, str(MAINTENANCE_ROOT))

from lib.maintenance_run import atomic_write_json

SCHEMA_VERSION = "maintenance-phase0-baseline/v1"
DEFAULT_PHASE_TEMP_ROOT = Path("tmp") / "maintenance-plan-tests"
HOT_CONTEXT_RELATIVE_PATHS = [
    Path("context") / "active.md",
    Path("context") / "decisions.md",
    Path("context") / "projects" / "quant-pipeline.md",
    Path("context") / "projects" / "workbench-context.md",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_phase_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-").lower()
    return cleaned or "phase"


def file_record(path: Path) -> dict[str, Any]:
    path = Path(path)
    record: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
    }
    if path.exists():
        record["is_file"] = path.is_file()
        record["size_bytes"] = path.stat().st_size if path.is_file() else None
    return record


def load_json_if_present(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    path = Path(path)
    status = file_record(path)
    if not path.exists():
        status["json_status"] = "missing"
        return None, status
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        status["json_status"] = "invalid"
        status["error"] = str(exc)
        return None, status
    if not isinstance(payload, dict):
        status["json_status"] = "non_object"
        status["json_type"] = type(payload).__name__
        return None, status
    status["json_status"] = "ok"
    status["top_level_keys"] = sorted(payload.keys())[:30]
    return payload, status


def latest_child_dir(root: Path) -> Path | None:
    root = Path(root)
    if not root.exists():
        return None
    children = [path for path in root.iterdir() if path.is_dir()]
    if not children:
        return None
    return max(children, key=lambda path: path.stat().st_mtime)


def latest_pressure_run_summary(runs_root: Path) -> dict[str, Any]:
    latest = latest_child_dir(runs_root)
    if latest is None:
        return {
            "runs_root": str(runs_root),
            "latest_run_dir": None,
            "latest_envelope": file_record(runs_root / "<latest>" / "envelope.json"),
            "pressure_apply_manifest": file_record(runs_root / "<latest>" / "pressure-apply-manifest.json"),
        }

    envelope, envelope_status = load_json_if_present(latest / "envelope.json")
    manifest, manifest_status = load_json_if_present(latest / "pressure-apply-manifest.json")
    return {
        "runs_root": str(runs_root),
        "latest_run_dir": str(latest),
        "latest_envelope": {
            **envelope_status,
            "status": envelope.get("status") if envelope else None,
            "summary_line": envelope.get("summary_line") if envelope else None,
        },
        "pressure_apply_manifest": {
            **manifest_status,
            "mode": manifest.get("mode") if manifest else None,
            "no_op_reason": manifest.get("no_op_reason") if manifest else None,
            "source_mutated": manifest.get("source_mutated") if manifest else None,
        },
    }


def expected_jobs_from_self_check(path: Path) -> dict[str, Any]:
    path = Path(path)
    record = file_record(path)
    if not path.exists():
        return {**record, "jobs": [], "parse_status": "missing"}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return {**record, "jobs": [], "parse_status": "syntax_error", "error": str(exc)}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "EXPECTED_JOBS" not in names:
                continue
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, SyntaxError) as exc:
                return {**record, "jobs": [], "parse_status": "literal_error", "error": str(exc)}
            if isinstance(value, list) and all(isinstance(item, str) for item in value):
                return {**record, "jobs": value, "job_count": len(value), "parse_status": "ok"}
            return {**record, "jobs": [], "parse_status": "unexpected_value"}
    return {**record, "jobs": [], "parse_status": "missing_expected_jobs"}


def launchd_template_status(launchd_dir: Path, *, repo_root: Path) -> dict[str, Any]:
    launchd_dir = Path(launchd_dir)
    plists = sorted(launchd_dir.glob("*.plist")) if launchd_dir.exists() else []
    records: list[dict[str, Any]] = []
    temp_path_count = 0
    repo_root_missing_count = 0
    for plist in plists:
        text = plist.read_text(encoding="utf-8", errors="replace")
        has_temp_path = "/private/tmp/" in text
        has_repo_root = str(repo_root) in text
        temp_path_count += 1 if has_temp_path else 0
        repo_root_missing_count += 1 if not has_repo_root else 0
        records.append(
            {
                "path": str(plist),
                "size_bytes": plist.stat().st_size,
                "has_private_tmp_path": has_temp_path,
                "contains_repo_root": has_repo_root,
            }
        )
    return {
        "launchd_dir": str(launchd_dir),
        "plist_count": len(plists),
        "private_tmp_path_count": temp_path_count,
        "repo_root_missing_count": repo_root_missing_count,
        "plists": records,
    }


def capture_maintenance_phase0_baseline(repo_root: Path, *, generated_at_utc: str | None = None) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    maintenance_root = repo_root / "maintenance"
    workbench_root = repo_root / "workbench"
    orchestrator_root = repo_root / "orchestrator"

    script_usage, script_usage_status = load_json_if_present(
        maintenance_root / "orchestrator-repo-maintenance" / "generated" / "script-usage-summary.json"
    )
    scheduled_state, scheduled_state_status = load_json_if_present(
        maintenance_root / "orchestrator-repo-maintenance" / "generated" / "scheduled-maintenance-state.json"
    )
    learning_status, learning_status_record = load_json_if_present(
        orchestrator_root / "scripts" / ".runtime-state" / "learning-maintenance-plane-status.json"
    )
    lmd_status, lmd_status_record = load_json_if_present(
        orchestrator_root / "scripts" / ".runtime-state" / "lmd-causal-maintenance-status.json"
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_now_iso(),
        "repo_root": str(repo_root),
        "workbench_context": {
            "latest_pressure_run": latest_pressure_run_summary(
                maintenance_root / "workbench-context-maintenance" / "generated" / "runs"
            ),
            "hot_context_files": {
                str(path): file_record(workbench_root / path)
                for path in HOT_CONTEXT_RELATIVE_PATHS
            },
            "state_file": file_record(workbench_root / "context" / "state" / "context-pruning-state.json"),
        },
        "maintenance_self_check": {
            "expected_cron_jobs": expected_jobs_from_self_check(maintenance_root / "maintenance_self_check.py"),
        },
        "repo_hygiene": {
            "script_usage_summary": {
                **script_usage_status,
                "classified_script_count": (
                    script_usage.get("summary", {}).get("classified_script_count")
                    if isinstance(script_usage.get("summary"), dict)
                    else None
                )
                if script_usage
                else None,
            },
            "scheduled_state": {
                **scheduled_state_status,
                "last_success_at": scheduled_state.get("last_success_at") if scheduled_state else None,
            },
        },
        "learning_maintenance": {
            **learning_status_record,
            "status": learning_status.get("status") if learning_status else None,
            "ok": learning_status.get("ok") if learning_status else None,
        },
        "lmd_causal_maintenance": {
            **lmd_status_record,
            "status": lmd_status.get("status") if lmd_status else None,
            "last_success_at": lmd_status.get("last_success_at") if lmd_status else None,
            "last_failure_at": lmd_status.get("failed_at_utc") if lmd_status else None,
            "error_type": lmd_status.get("error_type") if lmd_status else None,
        },
        "launchd_path_status": launchd_template_status(
            orchestrator_root / "scripts" / "launchd",
            repo_root=orchestrator_root,
        ),
    }


def write_phase0_baseline(path: Path, baseline: dict[str, Any]) -> Path:
    return atomic_write_json(Path(path), baseline)


@contextmanager
def phase_test_root(
    phase_name: str,
    *,
    base_root: Path = DEFAULT_PHASE_TEMP_ROOT,
    run_id: str | None = None,
) -> Iterator[Path]:
    phase = safe_phase_name(phase_name)
    root = Path(base_root) / phase / (run_id or uuid.uuid4().hex)
    if root.exists():
        raise FileExistsError(f"phase test root already exists: {root}")
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
        if root.exists():
            raise RuntimeError(f"phase test root cleanup failed: {root}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a non-mutating Maintenance Phase 0 baseline")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    baseline = capture_maintenance_phase0_baseline(args.repo_root)
    write_phase0_baseline(args.output, baseline)
    if args.pretty:
        print(json.dumps(baseline, indent=2, sort_keys=True))
    else:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
