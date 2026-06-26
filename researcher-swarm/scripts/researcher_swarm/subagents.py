"""Leaf researcher subagent coordination contracts.

This module builds spawn plans only. Actual OpenClaw session creation remains a
control-plane operation outside Researcher Swarm library code.
"""

from __future__ import annotations

from typing import Any

from .assignments import validate_leaf_research_assignment


def build_leaf_researcher_spawn_plan(assignments: list[dict[str, Any]], *, max_concurrent: int = 5) -> dict[str, Any]:
    if max_concurrent < 1 or max_concurrent > 5:
        raise ValueError("max_concurrent must be between 1 and 5")
    assignment_refs: list[str] = []
    for assignment in assignments:
        validation = validate_leaf_research_assignment(assignment)
        if not validation.valid:
            raise ValueError("; ".join(validation.errors))
        assignment_refs.append(str(assignment["assignment_id"]))
    return {
        "schema_version": "leaf-researcher-spawn-plan/v1",
        "runtime_owner": "ADS Researcher Swarm",
        "launch_authority": "control_plane_only",
        "max_concurrent": max_concurrent,
        "assignment_refs": assignment_refs,
        "spawn_count": len(assignment_refs),
    }


__all__ = ["build_leaf_researcher_spawn_plan"]
