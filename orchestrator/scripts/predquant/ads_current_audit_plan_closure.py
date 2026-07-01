"""ADS current-audit remediation plan closure helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


CURRENT_AUDIT_PLAN_CLOSURE_SCHEMA_VERSION = "ads-current-audit-plan-closure/v1"
REQUIRED_COMPLETED_PHASES = tuple(range(10))
PHASE9_BATCH_SCHEMA_VERSION = "ads-phase9-representative-batch/v1"
LIVE_READINESS_SCHEMA_VERSION = "ads-live-readiness-report/v1"

_PHASE_HEADING_RE = re.compile(r"^## Phase (?P<number>\d+) - (?P<title>.+)$")
_STATUS_RE = re.compile(r"^Status:\s*(?P<status>.+)$")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if item not in (None, "")]


def _is_complete_status(status: str | None) -> bool:
    normalized = str(status or "").strip().lower()
    return normalized == "complete" or normalized.startswith("completed")


def parse_current_audit_plan_phase_statuses(plan_text: str) -> dict[int, dict[str, Any]]:
    """Parse numbered phase titles and status lines from the markdown plan."""

    phases: dict[int, dict[str, Any]] = {}
    current_phase: int | None = None
    for line in plan_text.splitlines():
        heading = _PHASE_HEADING_RE.match(line.strip())
        if heading:
            current_phase = int(heading.group("number"))
            phases[current_phase] = {
                "phase": current_phase,
                "title": heading.group("title").strip(),
                "status": None,
                "complete": False,
            }
            continue
        status = _STATUS_RE.match(line.strip())
        if status and current_phase is not None:
            value = status.group("status").strip()
            phases[current_phase]["status"] = value
            phases[current_phase]["complete"] = _is_complete_status(value)
    return phases


def load_current_audit_plan_phase_statuses(plan_path: Path | str) -> dict[int, dict[str, Any]]:
    return parse_current_audit_plan_phase_statuses(Path(plan_path).read_text(encoding="utf-8"))


def _phase_completion_summary(phase_statuses: dict[int, dict[str, Any]]) -> dict[str, Any]:
    missing = [phase for phase in REQUIRED_COMPLETED_PHASES if phase not in phase_statuses]
    incomplete = [
        phase
        for phase in REQUIRED_COMPLETED_PHASES
        if phase in phase_statuses and not phase_statuses[phase].get("complete")
    ]
    phase10 = phase_statuses.get(10)
    return {
        "required_completed_phases": list(REQUIRED_COMPLETED_PHASES),
        "completed_required_phases": [
            phase for phase in REQUIRED_COMPLETED_PHASES if phase_statuses.get(phase, {}).get("complete")
        ],
        "missing_required_phases": missing,
        "incomplete_required_phases": incomplete,
        "all_required_phase_checklists_evaluated": not missing and not incomplete,
        "phase10_current_status": phase10.get("status") if phase10 else None,
        "phase_statuses": [
            phase_statuses[phase]
            for phase in sorted(phase_statuses)
            if phase <= 10
        ],
    }


def _phase9_summary(phase9_report: dict[str, Any] | None) -> dict[str, Any]:
    report = _as_dict(phase9_report)
    schema_ok = report.get("schema_version") == PHASE9_BATCH_SCHEMA_VERSION
    ok = bool(report.get("ok")) and report.get("status") == "passed" and schema_ok
    return {
        "schema_version": report.get("schema_version"),
        "schema_ok": schema_ok,
        "ok": ok,
        "status": report.get("status") or "missing",
        "issues": _string_list(report.get("issues")),
        "case_count": int(report.get("case_count") or 0),
        "scoreable_success_count": int(report.get("scoreable_success_count") or 0),
        "unexpected_failure_count": int(report.get("unexpected_failure_count") or 0),
        "clone_only_case_count": int(report.get("clone_only_case_count") or 0),
        "missing_representative_tags": _string_list(report.get("missing_representative_tags")),
    }


def _cal001_summary(live_readiness_report: dict[str, Any]) -> dict[str, Any]:
    calibration = _as_dict(live_readiness_report.get("calibration_debt_report"))
    if "clears_calibration_debt" not in calibration:
        return {
            "status": "missing",
            "honestly_represented": False,
            "clears_calibration_debt": None,
            "feature_id": calibration.get("feature_id"),
        }
    clears = bool(calibration.get("clears_calibration_debt"))
    return {
        "status": "cleared" if clears else "not_cleared",
        "honestly_represented": True,
        "clears_calibration_debt": clears,
        "feature_id": calibration.get("feature_id") or "CAL-001",
    }


def _live_readiness_summary(live_readiness_report: dict[str, Any] | None) -> dict[str, Any]:
    report = _as_dict(live_readiness_report)
    schema_ok = report.get("schema_version") == LIVE_READINESS_SCHEMA_VERSION
    readiness_ready = (
        schema_ok
        and report.get("status") == "ready"
        and report.get("true_runtime_cutover_ready") is True
        and report.get("true_runtime_cutover_status") == "ready"
    )
    cal001 = _cal001_summary(report) if schema_ok else {
        "status": "missing",
        "honestly_represented": False,
        "clears_calibration_debt": None,
        "feature_id": None,
    }
    return {
        "schema_version": report.get("schema_version"),
        "schema_ok": schema_ok,
        "status": report.get("status") or "missing",
        "ok": bool(report.get("ok")) if schema_ok else False,
        "true_runtime_cutover_status": report.get("true_runtime_cutover_status") or "missing",
        "true_runtime_cutover_ready": bool(report.get("true_runtime_cutover_ready")) if schema_ok else False,
        "readiness_ready": readiness_ready,
        "live_db_mutation": report.get("live_db_mutation") or "unknown_or_live",
        "clone_only": bool(report.get("clone_only")) if schema_ok else False,
        "issues": _string_list(report.get("issues")),
        "cal001": cal001,
    }


def build_current_audit_plan_closure_report(
    *,
    phase_statuses: dict[int, dict[str, Any]],
    phase9_report: dict[str, Any] | None,
    live_readiness_report: dict[str, Any] | None,
    live_mutation_authorized: bool = False,
) -> dict[str, Any]:
    phase_completion = _phase_completion_summary(phase_statuses)
    phase9 = _phase9_summary(phase9_report)
    readiness = _live_readiness_summary(live_readiness_report)
    issues: list[str] = []
    remaining_blockers: list[str] = []
    blocking_phase = None

    if not phase_completion["all_required_phase_checklists_evaluated"]:
        issues.append("required_phase_not_complete")
        first_incomplete = (
            phase_completion["missing_required_phases"]
            or phase_completion["incomplete_required_phases"]
        )[0]
        blocking_phase = f"Phase {first_incomplete}"

    if not phase9["ok"]:
        issues.append("phase9_representative_batch_not_passed")
        blocking_phase = blocking_phase or "Phase 9"

    if not readiness["schema_ok"]:
        issues.append("live_readiness_report_missing_or_invalid")
    if not readiness["cal001"]["honestly_represented"]:
        issues.append("cal001_not_honestly_represented")
    if readiness["schema_ok"] and not readiness["readiness_ready"]:
        remaining_blockers.append(
            f"live_readiness:{readiness['true_runtime_cutover_status']}"
        )
        remaining_blockers.extend(f"live_readiness_issue:{issue}" for issue in readiness["issues"])
    if readiness["cal001"]["honestly_represented"] and not readiness["cal001"]["clears_calibration_debt"]:
        remaining_blockers.append("cal001_not_cleared")
    if not live_mutation_authorized:
        remaining_blockers.append("vm_live_mutation_authorization_required")

    if issues:
        plan_status = "blocked"
        next_state = "remediate_closure_blocker"
        live_cutover_decision = "blocked_closure_report_incomplete"
    elif live_mutation_authorized and readiness["readiness_ready"]:
        plan_status = "ready_for_live_cutover"
        next_state = "ready_for_vm_cutover_confirmation"
        live_cutover_decision = "ready_after_explicit_authorization"
    else:
        plan_status = "implementation_ready_for_vm_review"
        next_state = "awaiting_vm_review_and_live_authorization"
        live_cutover_decision = (
            "blocked_readiness_not_ready"
            if live_mutation_authorized
            else "blocked_vm_authorization_required"
        )

    return {
        "schema_version": CURRENT_AUDIT_PLAN_CLOSURE_SCHEMA_VERSION,
        "ok": plan_status != "blocked",
        "plan_status": plan_status,
        "next_state": next_state,
        "issues": sorted(set(issues)),
        "blocking_phase": blocking_phase,
        "remaining_blockers": sorted(set(remaining_blockers)),
        "live_mutation_authorized": bool(live_mutation_authorized),
        "live_cutover_decision": live_cutover_decision,
        "phase_completion": phase_completion,
        "phase9_representative_batch": phase9,
        "live_readiness": readiness,
    }


__all__ = [
    "CURRENT_AUDIT_PLAN_CLOSURE_SCHEMA_VERSION",
    "REQUIRED_COMPLETED_PHASES",
    "build_current_audit_plan_closure_report",
    "load_current_audit_plan_phase_statuses",
    "parse_current_audit_plan_phase_statuses",
]
