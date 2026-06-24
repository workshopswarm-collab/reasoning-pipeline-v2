"""ADS v2 evidence packet construction and validation."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from predquant.ads_case_contract import (
    CaseContractError,
    parse_timestamp,
    validate_ads_case_contract,
)
from predquant.ads_handoff import (
    ArtifactManifestContext,
    build_artifact_manifest,
    canonical_json,
    validate_artifact_manifest,
    write_artifact_manifest,
)


EVIDENCE_PACKET_SCHEMA_VERSION = "evidence-packet/v2"
EVIDENCE_PACKET_ARTIFACT_TYPE = "evidence-packet-v2"
SOURCE_OF_TRUTH_STATUSES = {"clear", "ambiguous", "unknown"}
CONTRACT_STRUCTURES = {"binary", "family_aware_binary_child", "other"}
FAMILY_MODES = {"standalone_binary", "family_aware_binary_child", "unknown"}


class EvidencePacketError(ValueError):
    """Raised when an evidence packet is malformed or cannot be built safely."""


def ensure_no_raw_payload_fields(value: Any, path: str = "packet") -> None:
    forbidden = {"raw_payload", "payload", "raw_content", "content", "body", "html", "page_text"}
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in forbidden:
                raise EvidencePacketError(f"{path}.{key} must not duplicate raw payload content")
            ensure_no_raw_payload_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            ensure_no_raw_payload_fields(child, f"{path}[{idx}]")


def snapshot_value(snapshot: sqlite3.Row | dict[str, Any] | None, key: str) -> Any:
    if snapshot is None:
        return None
    if isinstance(snapshot, sqlite3.Row):
        return snapshot[key] if key in snapshot.keys() else None
    return snapshot.get(key)


def default_side_mapping(outcome_type: str | None) -> dict[str, Any]:
    if outcome_type and str(outcome_type).lower() != "binary":
        return {
            "primary": {"outcome": "primary", "resolves_to": "market_primary_outcome"},
        }
    return {
        "yes": {"outcome": "yes", "resolves_to": "market_resolves_yes"},
        "no": {"outcome": "no", "resolves_to": "market_resolves_no"},
    }


def validate_side_mapping(side_mapping: dict[str, Any], outcome_type: str | None) -> None:
    if not isinstance(side_mapping, dict) or not side_mapping:
        raise EvidencePacketError("side_mapping must be a non-empty object")
    normalized_outcome_type = str(outcome_type or "").lower()
    if normalized_outcome_type in {"", "binary"}:
        if set(side_mapping) != {"yes", "no"}:
            raise EvidencePacketError("binary side_mapping must contain exactly yes and no")
        yes = side_mapping["yes"].get("resolves_to")
        no = side_mapping["no"].get("resolves_to")
        if not yes or not no or yes == no:
            raise EvidencePacketError("binary side_mapping must map yes/no to distinct outcomes")
    for side, mapping in side_mapping.items():
        if not isinstance(mapping, dict):
            raise EvidencePacketError(f"side_mapping.{side} must be an object")
        if not mapping.get("outcome") or not mapping.get("resolves_to"):
            raise EvidencePacketError(f"side_mapping.{side} requires outcome and resolves_to")


def build_axis_mapping(side_mapping: dict[str, Any], outcome_type: str | None) -> dict[str, Any]:
    validate_side_mapping(side_mapping, outcome_type)
    if set(side_mapping) == {"yes", "no"}:
        return {
            "probability_axis": "selected_market_yes_probability",
            "scale": "0_to_1",
            "favorable_side": "yes",
            "unfavorable_side": "no",
            "side_directions": {
                "yes": {
                    "higher_probability_means": side_mapping["yes"]["resolves_to"],
                    "lower_probability_means": side_mapping["no"]["resolves_to"],
                },
                "no": {
                    "higher_probability_means": side_mapping["no"]["resolves_to"],
                    "lower_probability_means": side_mapping["yes"]["resolves_to"],
                },
            },
        }
    primary_side = next(iter(side_mapping))
    return {
        "probability_axis": "selected_market_primary_probability",
        "scale": "0_to_1",
        "favorable_side": primary_side,
        "unfavorable_side": None,
        "side_directions": {
            primary_side: {
                "higher_probability_means": side_mapping[primary_side]["resolves_to"],
                "lower_probability_means": "not_" + str(side_mapping[primary_side]["resolves_to"]),
            },
        },
    }


def normalize_relation_constraints(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item]
    raise EvidencePacketError("relation_constraints must be a string or list")


def normalize_family_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "parent_event_id": row.get("parent_event_id"),
        "child_market_id": row.get("child_market_id") or row.get("selected_child_market_id"),
        "family_type": row.get("family_type", "unknown"),
        "relation_constraints": normalize_relation_constraints(row.get("relation_constraints")),
        "sibling_price": row.get("sibling_price", row.get("price")),
        "sibling_price_method": row.get("sibling_price_method", row.get("price_method")),
    }


def build_family_context(case_contract: dict[str, Any], family_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    market_identity = case_contract["market_identity"]
    selected_child_id = str(market_identity.get("external_market_id") or market_identity["internal_market_id"])
    rows = [normalize_family_row(row) for row in (family_rows or [])]
    if not rows:
        outcome_type = str(market_identity.get("outcome_type") or "").lower()
        mode = "standalone_binary" if outcome_type in {"", "binary"} else "unknown"
        return {
            "mode": mode,
            "parent_event_id": None,
            "selected_child_market_id": selected_child_id if mode == "standalone_binary" else None,
            "sibling_child_ids": [],
            "family_type": "none" if mode == "standalone_binary" else "unknown",
            "relation_constraints": [],
            "sibling_prices": [],
            "family_validation_flags": [],
        }

    selected_rows = [row for row in rows if str(row.get("child_market_id")) == selected_child_id]
    if not selected_rows:
        raise EvidencePacketError("family-aware context requires selected child market row")
    selected = selected_rows[0]
    if not selected.get("parent_event_id"):
        raise EvidencePacketError("family-aware context requires parent_event_id")
    constraints = selected.get("relation_constraints") or []
    if not constraints:
        raise EvidencePacketError("family-aware context requires relation_constraints")

    sibling_rows = [row for row in rows if str(row.get("child_market_id")) != selected_child_id]
    return {
        "mode": "family_aware_binary_child",
        "parent_event_id": selected["parent_event_id"],
        "selected_child_market_id": selected_child_id,
        "sibling_child_ids": [str(row["child_market_id"]) for row in sibling_rows if row.get("child_market_id")],
        "family_type": selected.get("family_type") or "unknown",
        "relation_constraints": constraints,
        "sibling_prices": [
            {
                "child_market_id": str(row["child_market_id"]),
                "price": row.get("sibling_price"),
                "price_method": row.get("sibling_price_method"),
                "context_only": True,
            }
            for row in sibling_rows
            if row.get("child_market_id") and row.get("sibling_price") is not None
        ],
        "family_validation_flags": ["sibling_prices_context_only"],
    }


def build_market_reality_constraints(
    case_contract: dict[str, Any],
    *,
    side_mapping: dict[str, Any] | None = None,
    source_of_truth_status: str = "unknown",
    contract_structure: str | None = None,
) -> dict[str, Any]:
    market_identity = case_contract["market_identity"]
    mapping = side_mapping or default_side_mapping(market_identity.get("outcome_type"))
    validate_side_mapping(mapping, market_identity.get("outcome_type"))
    if source_of_truth_status not in SOURCE_OF_TRUTH_STATUSES:
        raise EvidencePacketError(f"unknown source_of_truth_status: {source_of_truth_status}")
    structure = contract_structure or ("binary" if str(market_identity.get("outcome_type") or "").lower() in {"", "binary"} else "other")
    if structure not in CONTRACT_STRUCTURES:
        raise EvidencePacketError(f"unknown contract_structure: {structure}")
    return {
        "side_mapping": mapping,
        "axis_mapping": build_axis_mapping(mapping, market_identity.get("outcome_type")),
        "source_of_truth_status": source_of_truth_status,
        "contract_structure": structure,
        "close_timestamp": market_identity.get("closes_at"),
        "resolve_timestamp": market_identity.get("resolves_at"),
    }


def build_prior_context_seed(
    case_contract: dict[str, Any],
    market_snapshot: sqlite3.Row | dict[str, Any] | None,
    quote_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    baseline = case_contract["prediction_time_market_baseline"]
    return {
        "market_live_probability": baseline.get("market_probability"),
        "market_probability_method": baseline.get("market_probability_method"),
        "market_snapshot_id": baseline.get("market_snapshot_id"),
        "market_snapshot_timestamp": baseline.get("source_fetched_at") or case_contract["source_cutoff_timestamp"],
        "snapshot_age_seconds_at_dispatch": baseline.get("snapshot_age_seconds_at_dispatch"),
        "quote_observation_refs": quote_refs or [],
        "microstructure_input_refs": [],
        "market_priced_through_timestamp": case_contract["source_cutoff_timestamp"],
        "compact_snapshot_fields": {
            "last_price": snapshot_value(market_snapshot, "last_price"),
            "best_bid": snapshot_value(market_snapshot, "best_bid"),
            "best_ask": snapshot_value(market_snapshot, "best_ask"),
            "yes_price": snapshot_value(market_snapshot, "yes_price"),
            "no_price": snapshot_value(market_snapshot, "no_price"),
            "volume": snapshot_value(market_snapshot, "volume"),
            "open_interest": snapshot_value(market_snapshot, "open_interest"),
        },
    }


def build_regime_seed_fields(case_contract: dict[str, Any], family_context: dict[str, Any]) -> dict[str, Any]:
    market_identity = case_contract["market_identity"]
    return {
        "platform": market_identity.get("platform"),
        "category": market_identity.get("category"),
        "status": market_identity.get("status"),
        "outcome_type": market_identity.get("outcome_type"),
        "contract_structure": "family_aware_binary_child"
        if family_context["mode"] == "family_aware_binary_child"
        else "binary",
        "family_type": family_context.get("family_type"),
        "close_timestamp": market_identity.get("closes_at"),
        "resolve_timestamp": market_identity.get("resolves_at"),
    }


def build_evidence_packet_v2(
    *,
    case_contract: dict[str, Any],
    case_contract_ref: str,
    market_snapshot: sqlite3.Row | dict[str, Any] | None = None,
    family_rows: list[dict[str, Any]] | None = None,
    quote_refs: list[dict[str, Any]] | None = None,
    side_mapping: dict[str, Any] | None = None,
    source_of_truth_status: str = "unknown",
) -> dict[str, Any]:
    try:
        validate_ads_case_contract(case_contract)
    except CaseContractError as exc:
        raise EvidencePacketError(f"invalid ADS case contract: {exc}") from exc

    family_context = build_family_context(case_contract, family_rows)
    structure = "family_aware_binary_child" if family_context["mode"] == "family_aware_binary_child" else "binary"
    constraints = build_market_reality_constraints(
        case_contract,
        side_mapping=side_mapping,
        source_of_truth_status=source_of_truth_status,
        contract_structure=structure,
    )
    packet = {
        "artifact_type": "evidence_packet",
        "schema_version": EVIDENCE_PACKET_SCHEMA_VERSION,
        "case_contract_ref": case_contract_ref,
        "case_id": case_contract["case_id"],
        "case_key": case_contract["case_key"],
        "market_id": case_contract["market_identity"]["internal_market_id"],
        "dispatch_id": case_contract["dispatch_id"],
        "forecast_timestamp": case_contract["forecast_timestamp"],
        "source_cutoff_timestamp": case_contract["source_cutoff_timestamp"],
        "market_identity": dict(case_contract["market_identity"]),
        "market_reality_constraints": constraints,
        "family_context": family_context,
        "prior_context_seed": build_prior_context_seed(case_contract, market_snapshot, quote_refs),
        "regime_seed_fields": build_regime_seed_fields(case_contract, family_context),
        "active_safe_refs": {
            "ads_case_contract": case_contract_ref,
            "source_payload_hash": case_contract["intake_source"]["source_payload_hash"],
            "market_snapshot_id": case_contract["intake_source"]["market_snapshot_id"],
        },
    }
    validate_evidence_packet_v2(packet)
    return packet


def validate_evidence_packet_v2(packet: dict[str, Any]) -> None:
    required = [
        "artifact_type",
        "schema_version",
        "case_contract_ref",
        "case_id",
        "case_key",
        "market_id",
        "dispatch_id",
        "forecast_timestamp",
        "source_cutoff_timestamp",
        "market_identity",
        "market_reality_constraints",
        "family_context",
        "prior_context_seed",
        "regime_seed_fields",
        "active_safe_refs",
    ]
    for field in required:
        if field not in packet:
            raise EvidencePacketError(f"{field} is required")
    if packet["artifact_type"] != "evidence_packet":
        raise EvidencePacketError("artifact_type must be evidence_packet")
    if packet["schema_version"] != EVIDENCE_PACKET_SCHEMA_VERSION:
        raise EvidencePacketError(f"schema_version must be {EVIDENCE_PACKET_SCHEMA_VERSION}")
    if not packet["case_contract_ref"]:
        raise EvidencePacketError("case_contract_ref is required")
    parse_timestamp(packet["forecast_timestamp"], "forecast_timestamp")
    parse_timestamp(packet["source_cutoff_timestamp"], "source_cutoff_timestamp")
    constraints = packet["market_reality_constraints"]
    validate_side_mapping(constraints.get("side_mapping"), packet["market_identity"].get("outcome_type"))
    axis_mapping = constraints.get("axis_mapping")
    if not isinstance(axis_mapping, dict) or not axis_mapping.get("probability_axis"):
        raise EvidencePacketError("market_reality_constraints.axis_mapping is required")
    if axis_mapping.get("scale") != "0_to_1":
        raise EvidencePacketError("axis_mapping.scale must be 0_to_1")
    if constraints.get("source_of_truth_status") not in SOURCE_OF_TRUTH_STATUSES:
        raise EvidencePacketError("invalid source_of_truth_status")
    if constraints.get("contract_structure") not in CONTRACT_STRUCTURES:
        raise EvidencePacketError("invalid contract_structure")
    family = packet["family_context"]
    if family.get("mode") not in FAMILY_MODES:
        raise EvidencePacketError("invalid family context mode")
    if family["mode"] == "family_aware_binary_child":
        if not family.get("selected_child_market_id"):
            raise EvidencePacketError("family-aware packet requires selected child")
        if not family.get("parent_event_id"):
            raise EvidencePacketError("family-aware packet requires parent event")
        if not family.get("relation_constraints"):
            raise EvidencePacketError("family-aware packet requires relation constraints")
        for sibling in family.get("sibling_prices", []):
            if not sibling.get("context_only"):
                raise EvidencePacketError("sibling prices must be context-only")
            if sibling.get("child_market_id") == family.get("selected_child_market_id"):
                raise EvidencePacketError("selected child cannot appear as sibling price")
    ensure_no_raw_payload_fields(packet)


def evidence_packet_path(artifact_dir: Path | str, packet: dict[str, Any]) -> Path:
    base = Path(artifact_dir) / packet["case_id"]
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{packet['dispatch_id']}-evidence-packet-v2.json"


def write_evidence_packet_artifact(path: Path | str, packet: dict[str, Any]) -> Path:
    validate_evidence_packet_v2(packet)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(packet) + "\n", encoding="utf-8")
    return target


def build_manifest_for_evidence_packet(packet: dict[str, Any], path: Path | str) -> dict[str, Any]:
    context = ArtifactManifestContext(
        case_id=packet["case_id"],
        case_key=packet["case_key"],
        dispatch_id=packet["dispatch_id"],
        stage="evidence_packet",
        producer="session-02-evidence-packet",
        forecast_timestamp=packet["forecast_timestamp"],
        source_cutoff_timestamp=packet["source_cutoff_timestamp"],
    )
    manifest = build_artifact_manifest(
        context=context,
        artifact_type=EVIDENCE_PACKET_ARTIFACT_TYPE,
        artifact_schema_version=EVIDENCE_PACKET_SCHEMA_VERSION,
        path=path,
        input_manifest_ids=[packet["case_contract_ref"]],
        validation_status="valid",
        validator_version="evidence-packet-v2",
        temporal_isolation_status="pass",
        metadata={
            "market_id": packet["market_id"],
            "market_snapshot_id": packet["prior_context_seed"].get("market_snapshot_id"),
            "family_mode": packet["family_context"]["mode"],
            "case_contract_ref": packet["case_contract_ref"],
        },
    )
    validate_artifact_manifest(manifest, expected_artifact_schema_version=EVIDENCE_PACKET_SCHEMA_VERSION)
    return manifest


def materialize_evidence_packet_v2(
    conn: sqlite3.Connection,
    *,
    case_contract: dict[str, Any],
    case_contract_ref: str,
    artifact_dir: Path | str,
    market_snapshot: sqlite3.Row | dict[str, Any] | None = None,
    family_rows: list[dict[str, Any]] | None = None,
    quote_refs: list[dict[str, Any]] | None = None,
    side_mapping: dict[str, Any] | None = None,
    source_of_truth_status: str = "unknown",
) -> dict[str, Any]:
    packet = build_evidence_packet_v2(
        case_contract=case_contract,
        case_contract_ref=case_contract_ref,
        market_snapshot=market_snapshot,
        family_rows=family_rows,
        quote_refs=quote_refs,
        side_mapping=side_mapping,
        source_of_truth_status=source_of_truth_status,
    )
    path = write_evidence_packet_artifact(evidence_packet_path(artifact_dir, packet), packet)
    manifest = build_manifest_for_evidence_packet(packet, path)
    artifact_id = write_artifact_manifest(conn, manifest)
    return {
        "status": "completed",
        "artifact_id": artifact_id,
        "artifact_path": str(path),
        "packet": packet,
        "manifest": manifest,
    }


def load_json_path(path: Path | None, default: Any) -> Any:
    if path is None:
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an ADS evidence packet v2 artifact.")
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--case-contract-path", required=True, type=Path)
    parser.add_argument("--case-contract-ref", required=True)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--family-rows-json", type=Path)
    parser.add_argument("--quote-refs-json", type=Path)
    parser.add_argument("--side-mapping-json", type=Path)
    parser.add_argument("--source-of-truth-status", default="unknown")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    contract = json.loads(args.case_contract_path.read_text(encoding="utf-8"))
    family_rows = load_json_path(args.family_rows_json, [])
    quote_refs = load_json_path(args.quote_refs_json, [])
    side_mapping = load_json_path(args.side_mapping_json, None)
    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            result = materialize_evidence_packet_v2(
                conn,
                case_contract=contract,
                case_contract_ref=args.case_contract_ref,
                artifact_dir=args.artifact_dir,
                family_rows=family_rows,
                quote_refs=quote_refs,
                side_mapping=side_mapping,
                source_of_truth_status=args.source_of_truth_status,
            )
        print(canonical_json({k: v for k, v in result.items() if k not in {"packet", "manifest"}}))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
