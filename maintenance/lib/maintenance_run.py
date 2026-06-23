#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "maintenance-run-envelope/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_run_id(prefix: str) -> str:
    safe_prefix = re.sub(r"[^A-Za-z0-9_.-]+", "-", prefix.strip()).strip("-").lower() or "maintenance"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{safe_prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


class MaintenanceRunError(RuntimeError):
    error_type = "maintenance_run_error"


class PreflightError(MaintenanceRunError):
    error_type = "preflight"


class StateParseError(MaintenanceRunError):
    error_type = "state_parse"


class SubprocessFailedError(MaintenanceRunError):
    error_type = "subprocess_failed"

    def __init__(self, message: str, proc: subprocess.CompletedProcess[str]) -> None:
        super().__init__(message)
        self.proc = proc


def atomic_write_text(path: Path, content: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
    return path


def atomic_write_json(path: Path, payload: Any) -> Path:
    return atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def load_json_with_context(path: Path) -> Any:
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StateParseError(f"missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise StateParseError(f"invalid JSON in {path}: {exc}") from exc


def preflight_path_exists(path: Path, label: str) -> None:
    path = Path(path)
    if not path.exists():
        raise PreflightError(f"{label} missing: {path}")


def preflight_writable_dir(path: Path, label: str) -> None:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise PreflightError(f"{label} is not a directory: {path}")
    probe = path / f".write-test-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        probe.write_text("", encoding="utf-8")
    except OSError as exc:
        raise PreflightError(f"{label} is not writable: {path}: {exc}") from exc
    finally:
        try:
            probe.unlink()
        except FileNotFoundError:
            pass


def _stringify_cmd(cmd: list[str]) -> str:
    return " ".join(str(part) for part in cmd)


@dataclass
class RunEnvelope:
    job_name: str
    mode: str
    runs_root: Path
    workspace_root: Path
    run_id: str
    started_at_utc: str = field(default_factory=utc_now_iso)
    warnings: list[str] = field(default_factory=list)
    artifact_paths: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.runs_root = Path(self.runs_root)
        self.workspace_root = Path(self.workspace_root)
        self.run_dir = self.runs_root / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.envelope_path = self.run_dir / "envelope.json"
        self._write_envelope(status="running", summary_line="", returncode=None)

    def add_artifact(self, path: Path) -> None:
        artifact = str(Path(path))
        if artifact not in self.artifact_paths:
            self.artifact_paths.append(artifact)

    def write_artifact(self, name: str, content: str) -> Path:
        if Path(name).name != name:
            raise ValueError(f"artifact name must be a file name, got: {name!r}")
        path = self.run_dir / name
        atomic_write_text(path, content)
        self.add_artifact(path)
        return path

    def run_subprocess(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        label: str,
    ) -> subprocess.CompletedProcess[str]:
        return self._run_subprocess_attempt(cmd, cwd=Path(cwd), label=label, attempt=1)

    def run_subprocess_with_retries(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        label: str,
        attempts: int = 2,
        backoff_seconds: float = 1.0,
    ) -> subprocess.CompletedProcess[str]:
        attempts = max(1, int(attempts))
        last_error: SubprocessFailedError | None = None
        for attempt in range(1, attempts + 1):
            try:
                return self._run_subprocess_attempt(cmd, cwd=Path(cwd), label=label, attempt=attempt)
            except SubprocessFailedError as exc:
                last_error = exc
                if attempt < attempts:
                    self.warnings.append(
                        f"{label} attempt {attempt} failed rc={exc.proc.returncode}; retrying"
                    )
                    time.sleep(max(0.0, float(backoff_seconds)))
        if last_error is not None:
            raise last_error
        raise SubprocessFailedError(
            f"subprocess failed without result: {_stringify_cmd(cmd)}",
            subprocess.CompletedProcess(cmd, 1, "", ""),
        )

    def _run_subprocess_attempt(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        label: str,
        attempt: int,
    ) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [str(part) for part in cmd],
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-") or "command"
        self.write_artifact(f"{safe_label}.attempt-{attempt}.stdout.txt", proc.stdout or "")
        self.write_artifact(f"{safe_label}.attempt-{attempt}.stderr.txt", proc.stderr or "")
        if proc.returncode != 0:
            raise SubprocessFailedError(
                f"command failed rc={proc.returncode}: {_stringify_cmd(cmd)}",
                proc,
            )
        return proc

    def finish(
        self,
        *,
        status: str,
        summary_line: str,
        returncode: int,
        error: BaseException | None = None,
    ) -> None:
        self._write_envelope(
            status=status,
            summary_line=summary_line,
            returncode=returncode,
            error=error,
        )

    def _write_envelope(
        self,
        *,
        status: str,
        summary_line: str,
        returncode: int | None,
        error: BaseException | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "job_name": self.job_name,
            "mode": self.mode,
            "run_id": self.run_id,
            "status": status,
            "summary_line": summary_line,
            "returncode": returncode,
            "started_at_utc": self.started_at_utc,
            "updated_at_utc": utc_now_iso(),
            "workspace_root": str(self.workspace_root),
            "runs_root": str(self.runs_root),
            "run_dir": str(self.run_dir),
            "artifact_paths": list(self.artifact_paths),
            "warnings": list(self.warnings),
        }
        if status != "running":
            payload["finished_at_utc"] = utc_now_iso()
        if error is not None:
            payload["error"] = {
                "type": type(error).__name__,
                "error_type": getattr(error, "error_type", "unexpected_exception"),
                "message": str(error),
            }
        atomic_write_json(self.envelope_path, payload)


def envelope_ref(envelope: RunEnvelope) -> str:
    try:
        return str(envelope.envelope_path.relative_to(envelope.workspace_root))
    except ValueError:
        return str(envelope.envelope_path)


if __name__ == "__main__":
    print("maintenance_run.py provides shared helpers and is not a standalone command.")
    raise SystemExit(0)
