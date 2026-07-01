#!/usr/bin/env python3
"""Print an AMRG operator report for a related-market context artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.amrg import (  # noqa: E402
    OllamaEmbeddingClient,
    build_amrg_operator_report,
    build_amrg_vector_preflight_report,
    canonical_json,
)


def attach_alerts(report: dict) -> dict:
    alerts = []
    refresh_status_counts = report.get("refresh_status_counts") or {}
    report["refresh_status_counts"] = {
        str(key or "missing"): value for key, value in refresh_status_counts.items()
    }
    if report.get("vector_readiness_status") == "vector_required_but_unavailable":
        alerts.append(
            {
                "severity": "blocker",
                "code": "amrg_vector_required_but_unavailable",
                "message": "AMRG vector runtime is required but unavailable.",
                "remediation": "Run AMRG vector preflight, install the configured model, or make the dependency optional.",
            }
        )
    elif report.get("vector_readiness_status") == "vector_unavailable_allowed_weak_context":
        alerts.append(
            {
                "severity": "warning",
                "code": "amrg_vector_unavailable_allowed_weak_context",
                "message": "AMRG vector runtime is unavailable and only weak-context operation is allowed.",
                "remediation": "Run AMRG vector preflight or accept weak-context-only operation explicitly.",
            }
        )
    if report.get("assist_readiness_status") == "assist_failed":
        alerts.append(
            {
                "severity": "warning",
                "code": "amrg_assist_failed",
                "message": "AMRG model assist was requested but did not produce accepted advisory output.",
                "remediation": "Inspect AMRG model-assist provenance and forbidden-output diagnostics.",
            }
        )
    weak_count = sum(
        int((report.get("relationship_status_counts") or {}).get(status, 0))
        for status in (
            "weak_context_only",
            "timing_mismatch_weak_context_only",
            "model_assisted_weak_context_only",
        )
    )
    if weak_count:
        alerts.append(
            {
                "severity": "warning",
                "code": "amrg_weak_context_only",
                "message": "AMRG supplied weak-context-only hints.",
                "value": weak_count,
                "remediation": "Treat AMRG hints as decomposition context only.",
            }
        )
    if "missing" in report["refresh_status_counts"]:
        alerts.append(
            {
                "severity": "blocker",
                "code": "missing_amrg_refresh_status_for_promoted_effects",
                "message": "AMRG context has missing refresh lifecycle status.",
                "remediation": "Refresh or downgrade promoted AMRG effects before scoreable live operation.",
            }
        )
    report["alerts"] = alerts or [
        {
            "severity": "info",
            "code": "amrg_operator_report_no_alerts",
            "message": "AMRG report found no alert conditions.",
            "remediation": "No action required.",
        }
    ]
    report["alert_counts_by_severity"] = {
        severity: sum(1 for alert in report["alerts"] if alert["severity"] == severity)
        for severity in ("blocker", "warning", "info")
    }
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an AMRG operator report.")
    parser.add_argument("related_market_context", type=Path, nargs="?")
    parser.add_argument("--question-decomposition", type=Path)
    parser.add_argument("--retrieval-packet", type=Path)
    parser.add_argument("--vector-preflight", action="store_true")
    parser.add_argument("--vector-required", action="store_true")
    parser.add_argument("--allow-vector-pull", action="store_true")
    parser.add_argument("--ollama-host")
    parser.add_argument("--source-cutoff-timestamp")
    parser.add_argument("--include-alerts", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.vector_preflight:
        client = OllamaEmbeddingClient(args.ollama_host) if args.ollama_host else None
        report = build_amrg_vector_preflight_report(
            client=client,
            allow_pull=args.allow_vector_pull,
            vector_required=args.vector_required,
            source_cutoff_timestamp=args.source_cutoff_timestamp,
        )
        if args.pretty:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(canonical_json(report))
        return 0
    if args.related_market_context is None:
        raise SystemExit("related_market_context is required unless --vector-preflight is set")
    context = json.loads(args.related_market_context.read_text(encoding="utf-8"))
    qdt = (
        json.loads(args.question_decomposition.read_text(encoding="utf-8"))
        if args.question_decomposition
        else None
    )
    retrieval_packet = (
        json.loads(args.retrieval_packet.read_text(encoding="utf-8"))
        if args.retrieval_packet
        else None
    )
    report = build_amrg_operator_report(
        context,
        question_decomposition=qdt,
        retrieval_packet=retrieval_packet,
    )
    if args.include_alerts:
        report = attach_alerts(report)
    if args.pretty:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
