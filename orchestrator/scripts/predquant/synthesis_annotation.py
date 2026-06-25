"""SYN-001 qualitative synthesis annotation contract.

Synthesis may summarize SCAE and research context, but it cannot author,
replace, persist, or score probabilities.
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


SYNTHESIS_ANNOTATION_SCHEMA_VERSION = "qualitative-synthesis-annotation/v1"
SYNTHESIS_ANNOTATION_ARTIFACT_TYPE = "qualitative_synthesis_annotation"
SYNTHESIS_ANNOTATION_AUTHORITY = "qualitative_annotation_only_no_probability_authority"
SYNTHESIS_ANNOTATION_BUILDER_VERSION = "ads-syn-001-qualitative-annotation/v1"
NO_LIVE_AUTHORITY = "none"

FORBIDDEN_SYNTHESIS_FIELD_NAMES = {
    "actionability_override",
    "actionability_status",
    "brier",
    "brier_score",
    "canonical_probability",
    "confidence_interval",
    "decision",
    "decision_override",
    "decision_recommendation",
    "debt_adjusted_probability",
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
    "prediction_brier",
    "probability",
    "probability_estimate",
    "probability_interval",
    "probability_override",
    "probability_range",
    "production_forecast_prob",
    "raw_ledger_probability",
    "recommended_decision",
    "replacement_probability",
    "scae_delta",
    "scae_log_odds_delta",
    "scoreable_forecast_output",
    "write_forecast_decision",
    "writes_persistence",
    "writes_production_forecast",
}
FORBIDDEN_SYNTHESIS_FIELD_KEYS = {
    re.sub(r"[^a-z0-9]", "", name.lower()) for name in FORBIDDEN_SYNTHESIS_FIELD_NAMES
}
FORBIDDEN_TEXT_PATTERN = re.compile(
    r"(?i)\b(?:probability|fair\s*value|forecast\s*prob|canonical\s*probability|production\s*forecast)"
    r"\b[^.\n]{0,80}(?:\d{1,3}(?:\.\d+)?\s*%|\b0\.\d+\b)"
)
ALLOWED_ANNOTATION_TYPES = {
    "qualitative_summary",
    "key_evidence",
    "uncertainty_driver",
    "research_gap",
    "watch_item",
    "scenario_note",
    "blocker",
    "rerun_recommendation",
}
ALLOWED_LEVERAGE_DIRECTIONS = {
    "supports_yes_qualitatively",
    "supports_no_qualitatively",
    "mixed_qualitative",
    "neutral_qualitative",
    "unclear_qualitative",
}


class SynthesisAnnotationError(ValueError):
    """Raised when SYN-001 annotation would violate authority boundaries."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _sha_id(prefix: str, value: Any, length: int = 24) -> str:
    return f"{prefix}-" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_non_empty(field_name: str, value: Any) -> str:
    if not _is_non_empty_string(value):
        raise SynthesisAnnotationError(f"{field_name} is required")
    return str(value)


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def ensure_no_synthesis_authority_fields(value: Any, path: str = "$") -> None:
    """Reject synthesis-authored probability, decision, persistence, or scoring fields."""

    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise SynthesisAnnotationError(f"{path} contains an invalid key")
            if _normalize_key(key) in FORBIDDEN_SYNTHESIS_FIELD_KEYS:
                raise SynthesisAnnotationError(f"{path}.{key} is forbidden for SYN-001")
            ensure_no_synthesis_authority_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            ensure_no_synthesis_authority_fields(child, f"{path}[{idx}]")
    elif isinstance(value, str):
        if FORBIDDEN_TEXT_PATTERN.search(value):
            raise SynthesisAnnotationError(f"{path} appears to author a numeric probability")
    elif value is None or isinstance(value, (bool, int, float)):
        return
    else:
        raise SynthesisAnnotationError(f"{path} contains unsupported type {type(value).__name__}")


def _string_list(field_name: str, value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SynthesisAnnotationError(f"{field_name} must be a list")
    normalized: list[str] = []
    for item in value:
        if not _is_non_empty_string(item):
            raise SynthesisAnnotationError(f"{field_name} must contain non-empty strings")
        normalized.append(str(item))
    return sorted(set(normalized))


def _rows_from(value: Any, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    rows = value.get(field_name) if isinstance(value, dict) and field_name in value else value
    if rows is None:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise SynthesisAnnotationError(f"{field_name} must be a list")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise SynthesisAnnotationError(f"{field_name} must contain objects")
        ensure_no_synthesis_authority_fields(row, field_name)
        normalized.append(copy.deepcopy(row))
    return normalized


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


def _validate_scae_ledger_input(ledger: dict[str, Any]) -> None:
    if not isinstance(ledger, dict):
        raise SynthesisAnnotationError("scae_ledger must be an object")
    _require_non_empty("scae_ledger.case_id", ledger.get("case_id"))
    _require_non_empty("scae_ledger.dispatch_id", ledger.get("dispatch_id"))
    _require_non_empty("scae_ledger.forecast_validity_status", ledger.get("forecast_validity_status"))
    _require_non_empty("scae_ledger.final_probability_fields_status", ledger.get("final_probability_fields_status"))
    if ledger.get("writes_persistence") is True:
        raise SynthesisAnnotationError("SCAE ledger input must not claim persistence write authority")
    if ledger.get("writes_production_forecast") is True:
        raise SynthesisAnnotationError("SCAE ledger input must not claim production forecast write authority")


def _scae_context(ledger: dict[str, Any]) -> dict[str, Any]:
    research_context = ledger.get("research_sufficiency_context")
    if not isinstance(research_context, dict):
        research_context = {}
    calibration_debt_context = ledger.get("calibration_debt_context")
    if not isinstance(calibration_debt_context, dict):
        calibration_debt_context = {}
    return {
        "scae_ledger_ref": _scae_ref(ledger),
        "scae_ledger_digest": _scae_digest(ledger),
        "schema_version": ledger.get("schema_version"),
        "case_id": ledger.get("case_id"),
        "case_key": ledger.get("case_key"),
        "dispatch_id": ledger.get("dispatch_id"),
        "run_id": ledger.get("run_id"),
        "forecast_timestamp": ledger.get("forecast_timestamp"),
        "forecast_validity_status": ledger.get("forecast_validity_status"),
        "execution_authority_status": ledger.get("execution_authority_status"),
        "final_probability_fields_status": ledger.get("final_probability_fields_status"),
        "research_sufficiency_context_ref": research_context.get("research_sufficiency_context_id"),
        "calibration_debt_context_ref": calibration_debt_context.get("calibration_debt_context_id"),
        "scae_owned_numeric_authority_refs": [
            "raw_ledger_probability",
            "post_ledger_probability",
            "debt_adjusted_probability",
            "production_forecast_prob",
            "canonical_probability",
        ],
    }


def _summary_ref(row: dict[str, Any], prefix: str) -> str:
    ref = _first_non_empty(
        row,
        (
            "summary_id",
            "artifact_id",
            "slice_id",
            "classification_summary_id",
            "research_summary_id",
            "classification_slice_id",
            "research_sufficiency_certificate_ref",
            "research_sufficiency_reconciliation_ref",
        ),
    )
    if ref:
        return ref
    return _sha_id(prefix, row)


def _normalize_summary_inputs(rows: list[dict[str, Any]], *, prefix: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        summary = {
            "summary_ref": _summary_ref(row, prefix),
            "artifact_type": row.get("artifact_type"),
            "schema_version": row.get("schema_version"),
            "leaf_id": row.get("leaf_id"),
            "parent_branch_id": row.get("parent_branch_id"),
            "condition_scope": row.get("condition_scope"),
            "source_refs": _string_list("source_refs", row.get("source_refs") or row.get("evidence_refs")),
            "reason_codes": _string_list("reason_codes", row.get("reason_codes")),
            "qualitative_summary": row.get("qualitative_summary") or row.get("summary") or row.get("finding"),
        }
        ensure_no_synthesis_authority_fields(summary, "summary_input")
        normalized.append(summary)
    return sorted(normalized, key=lambda item: str(item["summary_ref"]))


def _normalize_annotation_item(item: dict[str, Any], idx: int) -> dict[str, Any]:
    ensure_no_synthesis_authority_fields(item, f"qualitative_annotations[{idx}]")
    annotation_type = item.get("annotation_type", "qualitative_summary")
    if annotation_type not in ALLOWED_ANNOTATION_TYPES:
        raise SynthesisAnnotationError(f"unsupported annotation_type {annotation_type!r}")
    leverage_direction = item.get("leverage_direction", "unclear_qualitative")
    if leverage_direction not in ALLOWED_LEVERAGE_DIRECTIONS:
        raise SynthesisAnnotationError(f"unsupported leverage_direction {leverage_direction!r}")
    summary = _require_non_empty("annotation.summary", item.get("summary") or item.get("text"))
    normalized = {
        "annotation_id": item.get("annotation_id") or _sha_id("synthesis-annotation-item", item),
        "annotation_type": annotation_type,
        "summary": summary,
        "leverage_direction": leverage_direction,
        "source_refs": _string_list("annotation.source_refs", item.get("source_refs")),
        "reason_codes": _string_list("annotation.reason_codes", item.get("reason_codes")),
        "non_authoritative": True,
        "can_change_probability": False,
        "can_override_scae": False,
        "can_override_decision": False,
    }
    ensure_no_synthesis_authority_fields(normalized, f"qualitative_annotations[{idx}]")
    return normalized


def _default_annotation_items(
    classification_inputs: list[dict[str, Any]],
    research_inputs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_refs = sorted(
        {
            item["summary_ref"]
            for item in [*classification_inputs, *research_inputs]
            if _is_non_empty_string(item.get("summary_ref"))
        }
    )
    summary = (
        "Qualitative synthesis context assembled from "
        f"{len(classification_inputs)} classification summaries and "
        f"{len(research_inputs)} research summaries for SCAE-owned numeric review."
    )
    return [
        {
            "annotation_type": "qualitative_summary",
            "summary": summary,
            "leverage_direction": "unclear_qualitative",
            "source_refs": source_refs,
            "reason_codes": ["deterministic_syn001_context_only"],
        }
    ]


def validate_synthesis_annotation(annotation: dict[str, Any]) -> None:
    if not isinstance(annotation, dict):
        raise SynthesisAnnotationError("synthesis annotation must be an object")
    required = (
        "artifact_type",
        "schema_version",
        "feature_id",
        "authority",
        "scae_context",
        "qualitative_annotations",
        "forbidden_outputs",
    )
    for field_name in required:
        if field_name not in annotation:
            raise SynthesisAnnotationError(f"{field_name} is required")
    if annotation["artifact_type"] != SYNTHESIS_ANNOTATION_ARTIFACT_TYPE:
        raise SynthesisAnnotationError("artifact_type must be qualitative_synthesis_annotation")
    if annotation["schema_version"] != SYNTHESIS_ANNOTATION_SCHEMA_VERSION:
        raise SynthesisAnnotationError("unexpected synthesis annotation schema_version")
    if annotation["feature_id"] != "SYN-001":
        raise SynthesisAnnotationError("feature_id must be SYN-001")
    if annotation["authority"] != SYNTHESIS_ANNOTATION_AUTHORITY:
        raise SynthesisAnnotationError("authority must be qualitative annotation only")
    allowed_false_fields = {
        "live_forecast_authority",
        "probability_authority",
        "decision_authority",
        "persistence_authority",
        "scoring_authority",
        "writes_production_forecast",
        "writes_persistence",
    }
    for field_name in annotation:
        if field_name in {"scae_context", "forbidden_outputs"} | allowed_false_fields:
            continue
        if _normalize_key(field_name) in FORBIDDEN_SYNTHESIS_FIELD_KEYS:
            raise SynthesisAnnotationError(f"synthesis_annotation.{field_name} is forbidden for SYN-001")
    for field_name in (
        "classification_summary_inputs",
        "research_summary_inputs",
        "qualitative_annotations",
        "metadata",
    ):
        ensure_no_synthesis_authority_fields(annotation.get(field_name), f"synthesis_annotation.{field_name}")
    if annotation.get("live_authority") != NO_LIVE_AUTHORITY:
        raise SynthesisAnnotationError("live_authority must be none")
    for field_name in (
        *sorted(allowed_false_fields),
    ):
        if annotation.get(field_name) not in (False, 0):
            raise SynthesisAnnotationError(f"{field_name} must be false")
    expected_forbidden = {
        "probability",
        "probability_range",
        "fair_value",
        "interval_override",
        "scae_delta",
        "canonical_probability",
        "production_forecast_prob",
        "decision_or_actionability_override",
        "persistence_write",
        "scoreable_forecast_output",
    }
    if set(annotation["forbidden_outputs"]) != expected_forbidden:
        raise SynthesisAnnotationError("forbidden_outputs must match SYN-001 authority boundary")


def build_synthesis_annotation(
    *,
    scae_ledger: dict[str, Any],
    classification_summaries: list[dict[str, Any]] | dict[str, Any] | None = None,
    research_summaries: list[dict[str, Any]] | dict[str, Any] | None = None,
    qualitative_annotations: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a SYN-001 qualitative annotation artifact."""

    _validate_scae_ledger_input(scae_ledger)
    metadata = copy.deepcopy(metadata or {})
    if not isinstance(metadata, dict):
        raise SynthesisAnnotationError("metadata must be an object")
    ensure_no_synthesis_authority_fields(metadata, "metadata")
    classification_inputs = _normalize_summary_inputs(
        _rows_from(classification_summaries, "classification_summaries"),
        prefix="classification-summary",
    )
    research_inputs = _normalize_summary_inputs(
        _rows_from(research_summaries, "research_summaries"),
        prefix="research-summary",
    )
    annotation_items = qualitative_annotations or _default_annotation_items(classification_inputs, research_inputs)
    normalized_annotations = [
        _normalize_annotation_item(item, idx)
        for idx, item in enumerate(annotation_items)
    ]
    annotation = {
        "artifact_type": SYNTHESIS_ANNOTATION_ARTIFACT_TYPE,
        "schema_version": SYNTHESIS_ANNOTATION_SCHEMA_VERSION,
        "feature_id": "SYN-001",
        "builder_version": SYNTHESIS_ANNOTATION_BUILDER_VERSION,
        "authority": SYNTHESIS_ANNOTATION_AUTHORITY,
        "live_authority": NO_LIVE_AUTHORITY,
        "live_forecast_authority": False,
        "probability_authority": False,
        "decision_authority": False,
        "persistence_authority": False,
        "scoring_authority": False,
        "writes_production_forecast": False,
        "writes_persistence": False,
        "generated_at": generated_at or utc_now_iso(),
        "case_id": scae_ledger["case_id"],
        "case_key": scae_ledger.get("case_key"),
        "dispatch_id": scae_ledger["dispatch_id"],
        "scae_context": _scae_context(scae_ledger),
        "classification_summary_inputs": classification_inputs,
        "research_summary_inputs": research_inputs,
        "qualitative_annotations": sorted(
            normalized_annotations,
            key=lambda item: str(item["annotation_id"]),
        ),
        "allowed_outputs": [
            "qualitative_annotation",
            "qualitative_blockers",
            "qualitative_rerun_recommendations",
        ],
        "forbidden_outputs": sorted(
            [
                "probability",
                "probability_range",
                "fair_value",
                "interval_override",
                "scae_delta",
                "canonical_probability",
                "production_forecast_prob",
                "decision_or_actionability_override",
                "persistence_write",
                "scoreable_forecast_output",
            ]
        ),
        "metadata": metadata,
    }
    annotation["synthesis_annotation_id"] = _sha_id("synthesis-annotation", annotation)
    annotation["synthesis_annotation_digest"] = _prefixed_sha256(annotation)
    validate_synthesis_annotation(annotation)
    return annotation


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_many(paths: list[Path] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths or []:
        value = _load_json(path)
        if isinstance(value, list):
            rows.extend(value)
        elif isinstance(value, dict):
            rows.append(value)
        else:
            raise SynthesisAnnotationError(f"{path} must contain a JSON object or list")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a SYN-001 qualitative synthesis annotation.")
    parser.add_argument("--scae-ledger", required=True, type=Path)
    parser.add_argument("--classification-summary", action="append", type=Path, default=[])
    parser.add_argument("--research-summary", action="append", type=Path, default=[])
    parser.add_argument("--annotation", action="append", type=Path, default=[])
    parser.add_argument("--metadata-json", default="{}")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    metadata = json.loads(args.metadata_json)
    annotation = build_synthesis_annotation(
        scae_ledger=_load_json(args.scae_ledger),
        classification_summaries=_load_many(args.classification_summary),
        research_summaries=_load_many(args.research_summary),
        qualitative_annotations=_load_many(args.annotation) or None,
        metadata=metadata,
    )
    output = canonical_json(annotation)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
