"""DEC-001 decision and execution gate.

The gate consumes SCAE final probability fields and optional SYN-001
qualitative context, then emits only actionability/validity downgrades.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from predquant.synthesis_annotation import (
    SYNTHESIS_ANNOTATION_ARTIFACT_TYPE,
    validate_synthesis_annotation,
)


DECISION_GATE_SCHEMA_VERSION = "decision-execution-gate/v1"
DECISION_GATE_ARTIFACT_TYPE = "decision_execution_gate"
DECISION_GATE_AUTHORITY = "execution_downgrade_only_no_probability_authority"
DECISION_GATE_BUILDER_VERSION = "ads-dec-001-decision-gate/v1"

FORECAST_VALIDITY_RANK = {
    "invalid_for_forecast": 0,
    "valid_for_forecast_watch_only": 1,
    "valid_for_forecast": 2,
}
EXECUTION_AUTHORITY_RANK = {
    "forbidden": 0,
    "needs_refresh": 1,
    "watch_only": 2,
    "low_size_only": 3,
    "normal_execution_allowed": 4,
}
MAX_EXECUTION_BY_VALIDITY = {
    "invalid_for_forecast": "forbidden",
    "valid_for_forecast_watch_only": "watch_only",
    "valid_for_forecast": "normal_execution_allowed",
}
ACTIONABILITY_RANK = {
    "non_actionable": 0,
    "refresh_required": 1,
    "watch_only": 2,
    "actionable_low_size": 3,
    "actionable": 4,
}
DEFAULT_ACTIONABILITY_BY_EXECUTION = {
    "forbidden": "non_actionable",
    "needs_refresh": "refresh_required",
    "watch_only": "watch_only",
    "low_size_only": "actionable_low_size",
    "normal_execution_allowed": "actionable",
}

FORBIDDEN_DECISION_FIELD_NAMES = {
    "brier",
    "brier_score",
    "calibration_debt_cleared",
    "calibration_debt_clearance",
    "canonical_probability",
    "clear_calibration_debt",
    "confidence_interval",
    "debt_adjusted_probability",
    "decision_probability",
    "desired_probability",
    "fair_value",
    "fair_value_probability",
    "forecast_interval",
    "forecast_prob",
    "forecast_probability",
    "interval",
    "interval_override",
    "market_prediction",
    "market_predictions",
    "market_predictions_row",
    "persist_forecast",
    "persistence_write",
    "post_ledger_probability",
    "predicted_probability",
    "prediction_brier",
    "probability",
    "probability_estimate",
    "probability_interval",
    "probability_override",
    "probability_range",
    "probability_recommendation",
    "probability_signal",
    "production_forecast_prob",
    "raw_ledger_probability",
    "replacement_probability",
    "scae_delta",
    "scae_log_odds_delta",
    "scoreable_forecast_output",
    "scoreable_prediction",
    "target_probability",
    "write_forecast_decision",
    "writes_market_prediction",
    "writes_persistence",
    "writes_production_forecast",
}
FORBIDDEN_DECISION_FIELD_KEYS = {
    re.sub(r"[^a-z0-9]", "", name.lower()) for name in FORBIDDEN_DECISION_FIELD_NAMES
}
FORBIDDEN_TEXT_PATTERN = re.compile(
    r"(?i)\b(?:probability|fair\s*value|forecast\s*prob|canonical\s*probability|production\s*forecast)"
    r"\b[^.\n]{0,80}(?:\d{1,3}(?:\.\d+)?\s*%|\b0\.\d+\b)"
)


class DecisionGateError(ValueError):
    """Raised when DEC-001 would exceed decision/actionability authority."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _sha_id(prefix: str, value: Any, length: int = 24) -> str:
    return f"{prefix}-" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_non_empty(field_name: str, value: Any) -> str:
    if not _is_non_empty_string(value):
        raise DecisionGateError(f"{field_name} is required")
    return str(value)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not _is_non_empty_string(value):
        raise DecisionGateError("optional string fields must be non-empty strings")
    return str(value)


def _string_list(field_name: str, value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DecisionGateError(f"{field_name} must be a list")
    rows: list[str] = []
    for item in value:
        if not _is_non_empty_string(item):
            raise DecisionGateError(f"{field_name} must contain non-empty strings")
        rows.append(str(item))
    return sorted(set(rows))


def _validate_probability(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionGateError(f"{field_name} must be a numeric probability")
    probability = float(value)
    if not 0.0 <= probability <= 1.0:
        raise DecisionGateError(f"{field_name} must be in [0, 1]")
    return round(probability, 9)


def ensure_no_decision_numeric_authority_fields(value: Any, path: str = "$") -> None:
    """Reject decision-authored numeric forecast, persistence, scoring, and debt fields."""

    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise DecisionGateError(f"{path} contains an invalid key")
            if _normalize_key(key) in FORBIDDEN_DECISION_FIELD_KEYS:
                raise DecisionGateError(f"{path}.{key} is forbidden for DEC-001")
            ensure_no_decision_numeric_authority_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            ensure_no_decision_numeric_authority_fields(child, f"{path}[{idx}]")
    elif isinstance(value, str):
        if FORBIDDEN_TEXT_PATTERN.search(value):
            raise DecisionGateError(f"{path} appears to author a numeric probability")
    elif value is None or isinstance(value, (bool, int, float)):
        return
    else:
        raise DecisionGateError(f"{path} contains unsupported type {type(value).__name__}")


def _first_non_empty(row: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = row.get(field)
        if _is_non_empty_string(value):
            return str(value)
    return None


def _scae_ref(ledger: dict[str, Any]) -> str:
    ref = _first_non_empty(
        ledger,
        (
            "final_probability_ledger_id",
            "scae_ledger_id",
            "ledger_id",
            "research_sufficiency_guarded_ledger_id",
            "pre_debt_ledger_output_id",
        ),
    )
    if ref:
        return ref
    return _sha_id("scae-ledger", ledger)


def _scae_digest(ledger: dict[str, Any]) -> str:
    digest = _first_non_empty(
        ledger,
        (
            "final_probability_ledger_digest",
            "artifact_sha256",
            "scae_ledger_digest",
            "research_sufficiency_guarded_ledger_digest",
            "pre_debt_ledger_output_digest",
        ),
    )
    if digest:
        return digest
    return _prefixed_sha256(ledger)


def _validate_scae_ledger_input(ledger: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(ledger, dict):
        raise DecisionGateError("scae_ledger must be an object")
    _require_non_empty("scae_ledger.case_id", ledger.get("case_id"))
    _require_non_empty("scae_ledger.dispatch_id", ledger.get("dispatch_id"))
    validity = _require_non_empty("scae_ledger.forecast_validity_status", ledger.get("forecast_validity_status"))
    if validity not in FORECAST_VALIDITY_RANK:
        raise DecisionGateError(f"unknown SCAE forecast_validity_status {validity}")
    execution = _require_non_empty("scae_ledger.execution_authority_status", ledger.get("execution_authority_status"))
    if execution not in EXECUTION_AUTHORITY_RANK:
        raise DecisionGateError(f"unknown SCAE execution_authority_status {execution}")
    max_execution = MAX_EXECUTION_BY_VALIDITY[validity]
    if EXECUTION_AUTHORITY_RANK[execution] > EXECUTION_AUTHORITY_RANK[max_execution]:
        raise DecisionGateError("SCAE execution authority exceeds SCAE forecast validity")
    if ledger.get("writes_persistence") is True:
        raise DecisionGateError("SCAE ledger input must not claim persistence write authority")
    if ledger.get("writes_production_forecast") is True:
        raise DecisionGateError("SCAE ledger input must not claim production forecast write authority")

    if validity == "invalid_for_forecast":
        forbidden_present = sorted(
            field for field in ("production_forecast_prob", "canonical_probability") if field in ledger
        )
        if forbidden_present:
            raise DecisionGateError(
                "invalid SCAE forecast must not carry final production probability fields: "
                + ", ".join(forbidden_present)
            )
        return {"forecast_validity_status": validity, "execution_authority_status": execution}

    production = _validate_probability(ledger.get("production_forecast_prob"), "production_forecast_prob")
    canonical = _validate_probability(ledger.get("canonical_probability"), "canonical_probability")
    if canonical != production:
        raise DecisionGateError("canonical_probability must equal SCAE production_forecast_prob")
    final_status = _require_non_empty(
        "scae_ledger.final_probability_fields_status",
        ledger.get("final_probability_fields_status"),
    )
    if final_status != "final_probability_fields_ready":
        raise DecisionGateError("SCAE final probability fields must be ready")
    return {
        "forecast_validity_status": validity,
        "execution_authority_status": execution,
        "production_forecast_prob": production,
        "canonical_probability": canonical,
        "final_probability_fields_status": final_status,
    }


def _synthesis_ref(annotation: dict[str, Any]) -> str:
    ref = _first_non_empty(annotation, ("synthesis_annotation_id", "artifact_id"))
    if ref:
        return ref
    return _sha_id("synthesis-annotation", annotation)


def _synthesis_digest(annotation: dict[str, Any]) -> str:
    digest = _first_non_empty(annotation, ("synthesis_annotation_digest", "artifact_sha256"))
    if digest:
        return digest
    return _prefixed_sha256(annotation)


def _synthesis_context(annotation: dict[str, Any] | None) -> dict[str, Any]:
    if annotation is None:
        return {
            "synthesis_annotation_ref": None,
            "synthesis_annotation_digest": None,
            "qualitative_annotation_count": 0,
            "non_authoritative_context_only": True,
            "can_change_probability": False,
            "can_upgrade_execution": False,
        }
    if not isinstance(annotation, dict):
        raise DecisionGateError("synthesis_annotation must be an object")
    validate_synthesis_annotation(annotation)
    if annotation.get("artifact_type") != SYNTHESIS_ANNOTATION_ARTIFACT_TYPE:
        raise DecisionGateError("synthesis_annotation must be a SYN-001 artifact")
    annotations = annotation.get("qualitative_annotations") or []
    if not isinstance(annotations, list):
        raise DecisionGateError("synthesis_annotation.qualitative_annotations must be a list")
    return {
        "synthesis_annotation_ref": _synthesis_ref(annotation),
        "synthesis_annotation_digest": _synthesis_digest(annotation),
        "schema_version": annotation.get("schema_version"),
        "qualitative_annotation_count": len(annotations),
        "qualitative_annotation_refs": sorted(
            str(item.get("annotation_id"))
            for item in annotations
            if isinstance(item, dict) and _is_non_empty_string(item.get("annotation_id"))
        ),
        "qualitative_leverage_directions": sorted(
            set(
                str(item.get("leverage_direction"))
                for item in annotations
                if isinstance(item, dict) and _is_non_empty_string(item.get("leverage_direction"))
            )
        ),
        "non_authoritative_context_only": True,
        "can_change_probability": False,
        "can_upgrade_execution": False,
    }


def _requested_status(decision_request: dict[str, Any], *fields: str) -> str | None:
    for field in fields:
        value = decision_request.get(field)
        if value is not None:
            if not _is_non_empty_string(value):
                raise DecisionGateError(f"{field} must be a non-empty string")
            return str(value)
    return None


def _derive_statuses(
    *,
    scae_validity: str,
    scae_execution: str,
    decision_request: dict[str, Any],
) -> dict[str, Any]:
    requested_validity = _requested_status(
        decision_request,
        "forecast_validity_status",
        "decision_forecast_validity_status",
        "desired_forecast_validity_status",
    )
    effective_validity = requested_validity or scae_validity
    if effective_validity not in FORECAST_VALIDITY_RANK:
        raise DecisionGateError(f"unknown decision forecast_validity_status {effective_validity}")
    if FORECAST_VALIDITY_RANK[effective_validity] > FORECAST_VALIDITY_RANK[scae_validity]:
        raise DecisionGateError("decision/actionability cannot upgrade SCAE forecast validity")

    max_execution = min(
        EXECUTION_AUTHORITY_RANK[scae_execution],
        EXECUTION_AUTHORITY_RANK[MAX_EXECUTION_BY_VALIDITY[effective_validity]],
    )
    requested_execution = _requested_status(
        decision_request,
        "execution_authority_status",
        "desired_execution_authority_status",
        "decision_execution_authority_status",
    )
    effective_execution = requested_execution or scae_execution
    if effective_execution not in EXECUTION_AUTHORITY_RANK:
        raise DecisionGateError(f"unknown execution_authority_status {effective_execution}")
    if EXECUTION_AUTHORITY_RANK[effective_execution] > max_execution:
        raise DecisionGateError("decision/actionability cannot upgrade SCAE execution authority")

    default_actionability = DEFAULT_ACTIONABILITY_BY_EXECUTION[effective_execution]
    requested_actionability = _requested_status(
        decision_request,
        "actionability_status",
        "desired_actionability_status",
        "decision_actionability_status",
    )
    actionability = requested_actionability or default_actionability
    if actionability not in ACTIONABILITY_RANK:
        raise DecisionGateError(f"unknown actionability_status {actionability}")
    if ACTIONABILITY_RANK[actionability] > ACTIONABILITY_RANK[default_actionability]:
        raise DecisionGateError("actionability cannot exceed selected execution authority")

    scae_default_actionability = DEFAULT_ACTIONABILITY_BY_EXECUTION[scae_execution]
    return {
        "forecast_validity_status": effective_validity,
        "execution_authority_status": effective_execution,
        "actionability_status": actionability,
        "forecast_validity_downgraded": effective_validity != scae_validity,
        "execution_authority_downgraded": EXECUTION_AUTHORITY_RANK[effective_execution]
        < EXECUTION_AUTHORITY_RANK[scae_execution],
        "actionability_downgraded": ACTIONABILITY_RANK[actionability]
        < ACTIONABILITY_RANK[scae_default_actionability],
    }


def _decision_request(decision_request: dict[str, Any] | None) -> dict[str, Any]:
    if decision_request is None:
        return {}
    if not isinstance(decision_request, dict):
        raise DecisionGateError("decision_request must be an object")
    ensure_no_decision_numeric_authority_fields(decision_request, "decision_request")
    return copy.deepcopy(decision_request)


def _metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = copy.deepcopy(metadata or {})
    if not isinstance(metadata, dict):
        raise DecisionGateError("metadata must be an object")
    ensure_no_decision_numeric_authority_fields(metadata, "metadata")
    return metadata


def _scae_context(ledger: dict[str, Any], validated: dict[str, Any]) -> dict[str, Any]:
    context = {
        "scae_ledger_ref": _scae_ref(ledger),
        "scae_ledger_digest": _scae_digest(ledger),
        "schema_version": ledger.get("schema_version"),
        "case_id": ledger.get("case_id"),
        "case_key": ledger.get("case_key"),
        "dispatch_id": ledger.get("dispatch_id"),
        "run_id": ledger.get("run_id"),
        "forecast_timestamp": ledger.get("forecast_timestamp"),
        "forecast_validity_status": validated["forecast_validity_status"],
        "execution_authority_status": validated["execution_authority_status"],
        "final_probability_fields_status": ledger.get("final_probability_fields_status"),
        "probability_source": "SCAE-012_final_probability_fields",
    }
    if "production_forecast_prob" in validated:
        context["production_forecast_prob"] = validated["production_forecast_prob"]
        context["canonical_probability"] = validated["canonical_probability"]
    return context


def validate_decision_gate_artifact(artifact: dict[str, Any]) -> None:
    if not isinstance(artifact, dict):
        raise DecisionGateError("decision gate artifact must be an object")
    required = (
        "artifact_type",
        "schema_version",
        "feature_id",
        "authority",
        "scae_context",
        "forecast_validity_status",
        "execution_authority_status",
        "actionability_status",
        "forbidden_outputs",
    )
    for field_name in required:
        if field_name not in artifact:
            raise DecisionGateError(f"{field_name} is required")
    if artifact["artifact_type"] != DECISION_GATE_ARTIFACT_TYPE:
        raise DecisionGateError("artifact_type must be decision_execution_gate")
    if artifact["schema_version"] != DECISION_GATE_SCHEMA_VERSION:
        raise DecisionGateError("unexpected decision gate schema_version")
    if artifact["feature_id"] != "DEC-001":
        raise DecisionGateError("feature_id must be DEC-001")
    if artifact["authority"] != DECISION_GATE_AUTHORITY:
        raise DecisionGateError("authority must be downgrade-only")
    if not isinstance(artifact["scae_context"], dict):
        raise DecisionGateError("scae_context must be an object")

    allowed_false_fields = {
        "probability_authority",
        "replacement_probability_authority",
        "synthesis_upgrade_authority",
        "persistence_authority",
        "market_prediction_authority",
        "scoring_authority",
        "calibration_debt_clearance_authority",
        "writes_production_forecast",
        "writes_persistence",
        "writes_market_prediction",
        "scoreable_forecast_output",
        "clears_calibration_debt",
    }
    for field_name in allowed_false_fields:
        if artifact.get(field_name) not in (False, 0):
            raise DecisionGateError(f"{field_name} must be false")
    for field_name in artifact:
        if field_name in {"scae_context", "forbidden_outputs"} | allowed_false_fields:
            continue
        if _normalize_key(field_name) in FORBIDDEN_DECISION_FIELD_KEYS:
            raise DecisionGateError(f"decision_gate.{field_name} is forbidden for DEC-001")
    for field_name in ("decision_request_summary", "synthesis_context", "metadata"):
        ensure_no_decision_numeric_authority_fields(artifact.get(field_name), f"decision_gate.{field_name}")

    scae_validity = artifact["scae_context"].get("forecast_validity_status")
    scae_execution = artifact["scae_context"].get("execution_authority_status")
    if scae_validity not in FORECAST_VALIDITY_RANK:
        raise DecisionGateError("scae_context.forecast_validity_status is invalid")
    if scae_execution not in EXECUTION_AUTHORITY_RANK:
        raise DecisionGateError("scae_context.execution_authority_status is invalid")
    if artifact["forecast_validity_status"] not in FORECAST_VALIDITY_RANK:
        raise DecisionGateError("unknown forecast_validity_status")
    if artifact["execution_authority_status"] not in EXECUTION_AUTHORITY_RANK:
        raise DecisionGateError("unknown execution_authority_status")
    if FORECAST_VALIDITY_RANK[artifact["forecast_validity_status"]] > FORECAST_VALIDITY_RANK[scae_validity]:
        raise DecisionGateError("decision gate cannot upgrade SCAE forecast validity")
    if EXECUTION_AUTHORITY_RANK[artifact["execution_authority_status"]] > EXECUTION_AUTHORITY_RANK[scae_execution]:
        raise DecisionGateError("decision gate cannot upgrade SCAE execution authority")
    if artifact["actionability_status"] not in ACTIONABILITY_RANK:
        raise DecisionGateError("unknown actionability_status")
    default_actionability = DEFAULT_ACTIONABILITY_BY_EXECUTION[artifact["execution_authority_status"]]
    if ACTIONABILITY_RANK[artifact["actionability_status"]] > ACTIONABILITY_RANK[default_actionability]:
        raise DecisionGateError("actionability cannot exceed selected execution authority")
    expected_forbidden = {
        "replacement_probability",
        "probability_range",
        "fair_value",
        "interval_override",
        "scae_delta",
        "canonical_probability_override",
        "production_forecast_prob_override",
        "forecast_validity_upgrade",
        "persistence_write",
        "market_prediction_write",
        "scoreable_forecast_output",
        "calibration_debt_clearance",
    }
    if set(artifact["forbidden_outputs"]) != expected_forbidden:
        raise DecisionGateError("forbidden_outputs must match DEC-001 authority boundary")


def build_decision_gate(
    *,
    scae_ledger: dict[str, Any],
    synthesis_annotation: dict[str, Any] | None = None,
    decision_request: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a DEC-001 decision/actionability artifact."""

    validated_scae = _validate_scae_ledger_input(scae_ledger)
    request = _decision_request(decision_request)
    status = _derive_statuses(
        scae_validity=validated_scae["forecast_validity_status"],
        scae_execution=validated_scae["execution_authority_status"],
        decision_request=request,
    )
    reason_codes = _string_list("decision_request.reason_codes", request.get("reason_codes"))
    if not reason_codes:
        reason_codes = ["dec001_preserve_or_downgrade_scae_authority"]
    blockers = _string_list("decision_request.blocker_refs", request.get("blocker_refs"))
    source_refs = _string_list("decision_request.source_refs", request.get("source_refs"))
    artifact = {
        "artifact_type": DECISION_GATE_ARTIFACT_TYPE,
        "schema_version": DECISION_GATE_SCHEMA_VERSION,
        "feature_id": "DEC-001",
        "builder_version": DECISION_GATE_BUILDER_VERSION,
        "authority": DECISION_GATE_AUTHORITY,
        "probability_authority": False,
        "replacement_probability_authority": False,
        "synthesis_upgrade_authority": False,
        "persistence_authority": False,
        "market_prediction_authority": False,
        "scoring_authority": False,
        "calibration_debt_clearance_authority": False,
        "writes_production_forecast": False,
        "writes_persistence": False,
        "writes_market_prediction": False,
        "scoreable_forecast_output": False,
        "clears_calibration_debt": False,
        "generated_at": generated_at or utc_now_iso(),
        "case_id": scae_ledger["case_id"],
        "case_key": scae_ledger.get("case_key"),
        "dispatch_id": scae_ledger["dispatch_id"],
        "scae_context": _scae_context(scae_ledger, validated_scae),
        "synthesis_context": _synthesis_context(synthesis_annotation),
        "forecast_validity_status": status["forecast_validity_status"],
        "execution_authority_status": status["execution_authority_status"],
        "actionability_status": status["actionability_status"],
        "decision_request_summary": {
            "requested_forecast_validity_status": _requested_status(
                request,
                "forecast_validity_status",
                "decision_forecast_validity_status",
                "desired_forecast_validity_status",
            ),
            "requested_execution_authority_status": _requested_status(
                request,
                "execution_authority_status",
                "desired_execution_authority_status",
                "decision_execution_authority_status",
            ),
            "requested_actionability_status": _requested_status(
                request,
                "actionability_status",
                "desired_actionability_status",
                "decision_actionability_status",
            ),
            "rationale": _optional_string(request.get("rationale")),
            "reason_codes": reason_codes,
            "blocker_refs": blockers,
            "source_refs": source_refs,
        },
        "downgrade_context": {
            "forecast_validity_downgraded": status["forecast_validity_downgraded"],
            "execution_authority_downgraded": status["execution_authority_downgraded"],
            "actionability_downgraded": status["actionability_downgraded"],
            "can_upgrade_scae_validity": False,
            "can_replace_scae_probability": False,
            "synthesis_can_upgrade_execution": False,
        },
        "allowed_outputs": [
            "forecast_validity_downgrade",
            "execution_authority_downgrade",
            "non_actionable_status",
            "qualitative_rationale",
        ],
        "forbidden_outputs": sorted(
            [
                "replacement_probability",
                "probability_range",
                "fair_value",
                "interval_override",
                "scae_delta",
                "canonical_probability_override",
                "production_forecast_prob_override",
                "forecast_validity_upgrade",
                "persistence_write",
                "market_prediction_write",
                "scoreable_forecast_output",
                "calibration_debt_clearance",
            ]
        ),
        "metadata": _metadata(metadata),
    }
    artifact["decision_gate_id"] = _sha_id("decision-gate", artifact)
    artifact["decision_gate_digest"] = _prefixed_sha256(artifact)
    validate_decision_gate_artifact(artifact)
    return artifact


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a DEC-001 decision/actionability gate artifact.")
    parser.add_argument("--scae-ledger", required=True, type=Path)
    parser.add_argument("--synthesis-annotation", type=Path)
    parser.add_argument("--decision-request", type=Path)
    parser.add_argument("--metadata-json", default="{}")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    artifact = build_decision_gate(
        scae_ledger=_load_json(args.scae_ledger),
        synthesis_annotation=_load_json(args.synthesis_annotation) if args.synthesis_annotation else None,
        decision_request=_load_json(args.decision_request) if args.decision_request else None,
        metadata=json.loads(args.metadata_json),
    )
    output = canonical_json(artifact)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
