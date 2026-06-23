from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .paths import resolve_root


@dataclass(frozen=True)
class PathCandidate:
    root: str
    relative: str

    def resolve(self, *, openclaw_base: Path | None = None) -> Path:
        return resolve_root(self.root, openclaw_base=openclaw_base) / self.relative


@dataclass(frozen=True)
class Entrypoint:
    id: str
    candidates: tuple[PathCandidate, ...]
    kind: str = "file"


def _candidates(*items: tuple[str, str]) -> tuple[PathCandidate, ...]:
    return tuple(PathCandidate(root, relative) for root, relative in items)


def _script(root: str, relative: str) -> tuple[PathCandidate, ...]:
    return _candidates((root, relative))


def _researcher_script(relative: str) -> tuple[PathCandidate, ...]:
    return _script("orchestrator", f"runtime/researchers-swarm-subagents/{relative}")


def _synthesis_script(relative: str) -> tuple[PathCandidate, ...]:
    return _script("orchestrator", f"runtime/synthesis-subagent/{relative}")


def _decision_script(relative: str) -> tuple[PathCandidate, ...]:
    return _script("openclaw", f"decision-maker/{relative}")


def _evaluator_script(relative: str) -> tuple[PathCandidate, ...]:
    return _script("openclaw", f"evaluator/{relative}")


def _device_b_script(filename: str) -> tuple[PathCandidate, ...]:
    return _script("openclaw", f"device-b/scripts/{filename}")


ENTRYPOINTS: dict[str, Entrypoint] = {
    "researchers.manual_batch_controller": Entrypoint(
        "researchers.manual_batch_controller",
        _researcher_script("runtime/scripts/manual_batch_controller.py"),
    ),
    "researchers.reconcile_swarm_stage": Entrypoint(
        "researchers.reconcile_swarm_stage",
        _researcher_script("runtime/scripts/reconcile_swarm_stage.py"),
    ),
    "researchers.resume_swarm_stage": Entrypoint(
        "researchers.resume_swarm_stage",
        _researcher_script("runtime/scripts/resume_swarm_stage.py"),
    ),
    "researchers.select_refresh_case": Entrypoint(
        "researchers.select_refresh_case",
        _researcher_script("planner/scripts/select_refresh_case.py"),
    ),
    "researchers.sweep_orphaned_research_runs": Entrypoint(
        "researchers.sweep_orphaned_research_runs",
        _researcher_script("runtime/scripts/sweep_orphaned_research_runs.py"),
    ),
    "researchers.openclaw_sessions_send": Entrypoint(
        "researchers.openclaw_sessions_send",
        _researcher_script("runtime/scripts/internal/openclaw_sessions_send.mjs"),
    ),
    "researchers.telegram_topic_create": Entrypoint(
        "researchers.telegram_topic_create",
        _researcher_script("runtime/scripts/internal/telegram_topic_create.py"),
    ),
    "researchers.generate_evidence_packet_delta": Entrypoint(
        "researchers.generate_evidence_packet_delta",
        _researcher_script("planner/scripts/generate_evidence_packet_delta.py"),
    ),
    "researchers.generate_lmd_bundle": Entrypoint(
        "researchers.generate_lmd_bundle",
        _researcher_script("planner/scripts/generate_lmd_bundle.py"),
    ),
    "researchers.dispatch_manifests_dir": Entrypoint(
        "researchers.dispatch_manifests_dir",
        _candidates(("orchestrator", "runtime/researchers-swarm-subagents/runtime/dispatch-manifests")),
        kind="directory",
    ),
    "synthesis.launch_synthesis_if_ready": Entrypoint(
        "synthesis.launch_synthesis_if_ready",
        _synthesis_script("runtime/scripts/launch_synthesis_if_ready.py"),
    ),
    "synthesis.kickoff_synthesis_after_swarm": Entrypoint(
        "synthesis.kickoff_synthesis_after_swarm",
        _synthesis_script("runtime/scripts/kickoff_synthesis_after_swarm.py"),
    ),
    "decision.reconcile_decision_stage": Entrypoint(
        "decision.reconcile_decision_stage",
        _decision_script("runtime/scripts/reconcile_decision_stage.py"),
    ),
    "decision.finalize_decision_stage": Entrypoint(
        "decision.finalize_decision_stage",
        _decision_script("runtime/scripts/finalize_decision_stage.py"),
    ),
    "decision.run_decision_maker": Entrypoint(
        "decision.run_decision_maker",
        _decision_script("runtime/scripts/run_decision_maker.py"),
    ),
    "decision.run_light_refresh_update": Entrypoint(
        "decision.run_light_refresh_update",
        _decision_script("runtime/scripts/run_light_refresh_update.py"),
    ),
    "evaluator.backfill_case_review_bundles": Entrypoint(
        "evaluator.backfill_case_review_bundles",
        _evaluator_script("runtime/scripts/backfill_case_review_bundles.py"),
    ),
    "evaluator.materialize_analysis_factor_ledger": Entrypoint(
        "evaluator.materialize_analysis_factor_ledger",
        _evaluator_script("runtime/scripts/materialize_analysis_factor_ledger.py"),
    ),
    "evaluator.run_resolved_case_learning_sync": Entrypoint(
        "evaluator.run_resolved_case_learning_sync",
        _evaluator_script("runtime/scripts/run_resolved_case_learning_sync.py"),
    ),
    "evaluator.run_lmd_causal_maintenance_cycle": Entrypoint(
        "evaluator.run_lmd_causal_maintenance_cycle",
        _evaluator_script("runtime/scripts/run_lmd_causal_maintenance_cycle.py"),
    ),
    "evaluator.run_async_lmd_causal_maintenance": Entrypoint(
        "evaluator.run_async_lmd_causal_maintenance",
        _evaluator_script("runtime/scripts/run_async_lmd_causal_maintenance.py"),
    ),
    "evaluator.runtime_root": Entrypoint(
        "evaluator.runtime_root",
        _candidates(("openclaw", "evaluator/runtime")),
        kind="directory",
    ),
    "device_b.intake_filter": Entrypoint(
        "device_b.intake_filter",
        _device_b_script("1_intake_filter.py"),
    ),
    "device_b.push_to_db": Entrypoint(
        "device_b.push_to_db",
        _device_b_script("2_push_to_db.py"),
    ),
    "device_b.db_ingest": Entrypoint(
        "device_b.db_ingest",
        _device_b_script("3_db_ingest_script.py"),
    ),
}


def all_entrypoints() -> Iterable[Entrypoint]:
    return ENTRYPOINTS.values()


def resolve_entrypoint(entrypoint_id: str, *, openclaw_base: Path | None = None, require_exists: bool = True) -> Path:
    try:
        entrypoint = ENTRYPOINTS[entrypoint_id]
    except KeyError as exc:
        raise KeyError(f"unknown OpenClaw entrypoint: {entrypoint_id}") from exc

    resolved_candidates = [candidate.resolve(openclaw_base=openclaw_base) for candidate in entrypoint.candidates]
    for path in resolved_candidates:
        if path.exists():
            return path
    if not require_exists:
        return resolved_candidates[0]
    candidates = ", ".join(str(path) for path in resolved_candidates)
    raise FileNotFoundError(f"no path exists for OpenClaw entrypoint {entrypoint_id!r}; candidates: {candidates}")
