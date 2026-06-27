"""OpenClaw-backed Researcher Swarm runtime adapter.

The Researcher Swarm owns the artifact contract. OpenClaw owns OAuth-backed
Codex session execution. This module adapts the latter into the former without
giving researcher agents forecast, SCAE, or orchestration authority.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from typing import Any

from .subagents import validate_researcher_swarm_runtime_bundle


OPENCLAW_RESEARCHER_SWARM_AGENT_ID = "researcher-swarm"
OPENCLAW_RESEARCHER_SWARM_PROVIDER_ROUTE = "openclaw_codex_oauth/researcher-swarm"


class OpenClawResearcherRuntimeError(RuntimeError):
    """Raised when OpenClaw Researcher Swarm runtime fails closed."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _json_payload(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start >= 0 and end > start:
                return json.loads(stripped[start : end + 1])
            raise
    return value


def _extract_reply_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        texts = [_extract_reply_text(item) for item in value]
        joined = "\n".join(text for text in texts if text)
        return joined or None
    if not isinstance(value, dict):
        return None
    if value.get("artifact_type") == "researcher_swarm_runtime_bundle":
        return _canonical_json(value)
    for key in (
        "reply",
        "response",
        "message",
        "content",
        "text",
        "output",
        "stdout",
        "payloads",
        "finalAssistantVisibleText",
        "finalAssistantRawText",
    ):
        text = _extract_reply_text(value.get(key))
        if text:
            return text
    return _extract_reply_text(value.get("result"))


def parse_openclaw_researcher_swarm_stdout(stdout: str) -> dict[str, Any]:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        parsed = stdout
    text = _extract_reply_text(parsed)
    if not text:
        raise OpenClawResearcherRuntimeError("OpenClaw response did not contain reply text")
    bundle = _json_payload(text)
    if not isinstance(bundle, dict):
        raise OpenClawResearcherRuntimeError("OpenClaw reply did not parse to a runtime bundle object")
    validation = validate_researcher_swarm_runtime_bundle(bundle)
    if not validation.valid:
        raise OpenClawResearcherRuntimeError(
            "OpenClaw researcher runtime bundle invalid: " + "; ".join(validation.errors)
        )
    return bundle


def build_researcher_swarm_openclaw_prompt(
    *,
    assignments: list[dict[str, Any]],
    qdt: dict[str, Any],
    retrieval_packet: dict[str, Any],
    true_production_mode: bool,
    max_concurrent: int,
) -> str:
    envelope = {
        "schema_version": "researcher-swarm-openclaw-runtime-request/v1",
        "runtime_owner": "ADS Researcher Swarm",
        "runtime_provider_route": OPENCLAW_RESEARCHER_SWARM_PROVIDER_ROUTE,
        "true_production_mode": bool(true_production_mode),
        "max_concurrent": int(max_concurrent),
        "assignments": copy.deepcopy(assignments),
        "qdt": copy.deepcopy(qdt),
        "retrieval_packet": copy.deepcopy(retrieval_packet),
    }
    return (
        "You are ADS Researcher Swarm executing a certified leaf-research dispatch.\n\n"
        "Use fresh isolated, impermanent leaf subagent sessions for the dispatchable "
        "leaf assignments. Each leaf subagent may see only its own assignment, "
        "allowed artifact refs, and admitted evidence refs. Do not expose sibling "
        "assignments, peer outputs, aggregate summaries, SCAE refs, forecasts, "
        "decisions, scoring, replay, or outcomes. Clean up leaf sessions after "
        "their handoff where the runtime supports cleanup.\n\n"
        "Return exactly one JSON object and no Markdown: a valid "
        "researcher_swarm_runtime_bundle with schema_version "
        "researcher-swarm-runtime-bundle/v1. Include subagent session refs, "
        "isolation audit refs, sidecar refs, per-leaf model_executed=true runtime "
        "provenance for openai/gpt-5.5-high when a leaf model ran, and blocker "
        "statuses for leaves that cannot be resolved. Do not author probabilities, "
        "fair values, SCAE deltas, decisions, execution advice, or production "
        "forecast outputs.\n\n"
        "Runtime request JSON:\n"
        + _canonical_json(envelope)
    )


def run_openclaw_researcher_swarm_runtime(
    *,
    assignments: list[dict[str, Any]],
    qdt: dict[str, Any],
    retrieval_packet: dict[str, Any],
    true_production_mode: bool = True,
    max_concurrent: int = 5,
    agent_id: str | None = None,
    cli_path: str | None = None,
    session_key_prefix: str | None = None,
    timeout_seconds: int = 900,
    model: str | None = None,
) -> dict[str, Any]:
    resolved_agent_id = (
        agent_id
        or os.environ.get("ADS_RESEARCHER_SWARM_OPENCLAW_AGENT_ID")
        or OPENCLAW_RESEARCHER_SWARM_AGENT_ID
    )
    resolved_cli = cli_path or os.environ.get("ADS_OPENCLAW_CLI") or shutil.which("openclaw")
    if not resolved_cli:
        raise OpenClawResearcherRuntimeError("openclaw CLI is required for Researcher Swarm runtime")
    resolved_prefix = (
        session_key_prefix
        or os.environ.get("ADS_RESEARCHER_SWARM_OPENCLAW_SESSION_KEY_PREFIX")
        or "ads-researcher-swarm"
    )
    resolved_model = model or os.environ.get("ADS_RESEARCHER_SWARM_OPENCLAW_MODEL")
    case_id = str(retrieval_packet.get("case_id") or qdt.get("case_id") or "case")
    dispatch_id = str(retrieval_packet.get("dispatch_id") or qdt.get("dispatch_id") or "dispatch")
    session_key = f"{resolved_prefix}-{case_id}-{dispatch_id}".replace(":", "-")
    command = [
        resolved_cli,
        "agent",
        "--agent",
        resolved_agent_id,
        "--session-key",
        session_key,
        "--message",
        build_researcher_swarm_openclaw_prompt(
            assignments=assignments,
            qdt=qdt,
            retrieval_packet=retrieval_packet,
            true_production_mode=true_production_mode,
            max_concurrent=max_concurrent,
        ),
        "--json",
        "--timeout",
        str(timeout_seconds),
    ]
    if resolved_model:
        command.extend(["--model", resolved_model])
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds + 30,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise OpenClawResearcherRuntimeError(f"OpenClaw Researcher Swarm failed: {detail[:500]}")
    bundle = parse_openclaw_researcher_swarm_stdout(completed.stdout)
    provenance = copy.deepcopy(bundle.get("openclaw_runtime_provenance") or {})
    provenance.update(
        {
            "transport": "openclaw_agent",
            "auth_route": "openclaw_codex_oauth",
            "agent_id": resolved_agent_id,
            "session_key": session_key,
            "provider_route": OPENCLAW_RESEARCHER_SWARM_PROVIDER_ROUTE,
        }
    )
    bundle["openclaw_runtime_provenance"] = provenance
    return bundle


__all__ = [
    "OPENCLAW_RESEARCHER_SWARM_AGENT_ID",
    "OPENCLAW_RESEARCHER_SWARM_PROVIDER_ROUTE",
    "OpenClawResearcherRuntimeError",
    "build_researcher_swarm_openclaw_prompt",
    "parse_openclaw_researcher_swarm_stdout",
    "run_openclaw_researcher_swarm_runtime",
]
