"""Family-aware binary child diagnostics for ADS SCAE."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from scae.policy import default_scae_policy


SCAE_FAMILY_DIAGNOSTICS_SCHEMA_VERSION = "scae-family-diagnostics/v1"
SCAE_FAMILY_DIAGNOSTICS_ARTIFACT_TYPE = "scae_family_diagnostics"
SCAE_FAMILY_DIAGNOSTICS_AUTHORITY = "scae_family_diagnostics_context_only"
EVIDENCE_PACKET_SCHEMA_VERSION = "evidence-packet/v2"
DEFAULT_FAMILY_PRICE_TOLERANCE = 0.02

FORBIDDEN_AUTHORING_FIELDS = {
    "raw_ledger_probability",
    "post_ledger_probability",
    "debt_adjusted_probability",
    "production_forecast_prob",
    "canonical_probability",
    "posterior_probability",
    "forecast_probability",
    "prior_odds",
    "raw_market_log_odds",
    "adjusted_prior_log_odds",
    "adjusted_prior_probability",
    "evidence_delta",
    "scae_evidence_delta",
    "signed_delta",
    "log_odds_delta",
    "probability_update",
    "interval",
    "decision",
}


class ScaeFamilyDiagnosticsError(ValueError):
    """Raised when family-aware diagnostics are malformed or unsafe."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_id(prefix: str, value: Any) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}:{digest}"


def numeric_price(value: Any, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScaeFamilyDiagnosticsError(f"{field_name} must be a numeric market price")
    price = float(value)
    if not 0.0 <= price <= 1.0:
        raise ScaeFamilyDiagnosticsError(f"{field_name} must be in [0, 1]")
    return price


def family_diagnostics_policy(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    active_policy = policy or default_scae_policy()
    family_policy = dict(active_policy.get("family_diagnostics") or {})
    tolerance = family_policy.get("exclusive_family_price_tolerance", DEFAULT_FAMILY_PRICE_TOLERANCE)
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or tolerance < 0.0:
        raise ScaeFamilyDiagnosticsError("family diagnostic price tolerance must be non-negative")
    family_policy.setdefault("exclusive_family_price_tolerance", float(tolerance))
    family_policy.setdefault("sibling_prices_context_only", True)
    family_policy.setdefault("allow_sibling_price_evidence_updates", False)
    family_policy.setdefault("allow_sibling_softmax_reallocation", False)
    family_policy.setdefault("allow_sibling_price_probability_movement", False)
    if family_policy["sibling_prices_context_only"] is not True:
        raise ScaeFamilyDiagnosticsError("sibling prices must remain context-only")
    for field in [
        "allow_sibling_price_evidence_updates",
        "allow_sibling_softmax_reallocation",
        "allow_sibling_price_probability_movement",
    ]:
        if family_policy[field] is not False:
            raise ScaeFamilyDiagnosticsError(f"family_diagnostics.{field} must be false")
    return family_policy


def reject_forbidden_authoring_fields(value: Any, path: str = "diagnostics") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in FORBIDDEN_AUTHORING_FIELDS:
                raise ScaeFamilyDiagnosticsError(f"{path}.{key} is forbidden in family diagnostics")
            reject_forbidden_authoring_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            reject_forbidden_authoring_fields(child, f"{path}[{idx}]")


def validate_evidence_packet_family_input(evidence_packet: dict[str, Any]) -> None:
    if not isinstance(evidence_packet, dict):
        raise ScaeFamilyDiagnosticsError("evidence_packet must be an object")
    if evidence_packet.get("schema_version") != EVIDENCE_PACKET_SCHEMA_VERSION:
        raise ScaeFamilyDiagnosticsError(f"evidence_packet.schema_version must be {EVIDENCE_PACKET_SCHEMA_VERSION}")
    for field in ["case_id", "market_id", "dispatch_id", "family_context", "prior_context_seed"]:
        if field not in evidence_packet:
            raise ScaeFamilyDiagnosticsError(f"evidence_packet.{field} is required")
    if not isinstance(evidence_packet["family_context"], dict):
        raise ScaeFamilyDiagnosticsError("evidence_packet.family_context must be an object")
    if not isinstance(evidence_packet["prior_context_seed"], dict):
        raise ScaeFamilyDiagnosticsError("evidence_packet.prior_context_seed must be an object")


def normalize_sibling_prices(family_context: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    selected_child_value = family_context.get("selected_child_market_id")
    selected_child_id = str(selected_child_value) if selected_child_value is not None else None
    declared_sibling_ids = {
        str(child_id)
        for child_id in family_context.get("sibling_child_ids", [])
        if child_id is not None and child_id != ""
    }
    records: list[dict[str, Any]] = []
    flags: list[str] = []
    for idx, sibling in enumerate(family_context.get("sibling_prices", []) or []):
        if not isinstance(sibling, dict):
            raise ScaeFamilyDiagnosticsError(f"family_context.sibling_prices[{idx}] must be an object")
        child_id = sibling.get("child_market_id")
        if child_id is None or child_id == "":
            raise ScaeFamilyDiagnosticsError(f"family_context.sibling_prices[{idx}].child_market_id is required")
        child_id = str(child_id)
        if child_id == selected_child_id:
            raise ScaeFamilyDiagnosticsError("selected child cannot appear in sibling_prices")
        if sibling.get("context_only") is not True:
            raise ScaeFamilyDiagnosticsError("sibling prices must be context-only")
        if declared_sibling_ids and child_id not in declared_sibling_ids:
            flags.append("sibling_price_without_declared_sibling_id")
        records.append(
            {
                "child_market_id": child_id,
                "market_price": numeric_price(sibling.get("price"), f"family_context.sibling_prices[{idx}].price"),
                "price_method": sibling.get("price_method"),
                "context_only": True,
            }
        )
    return records, sorted(set(flags))


def strongest_sibling(sibling_prices: list[dict[str, Any]]) -> dict[str, Any] | None:
    known = [record for record in sibling_prices if record["market_price"] is not None]
    if not known:
        return None
    selected = max(known, key=lambda record: (record["market_price"], record["child_market_id"]))
    return {
        "child_market_id": selected["child_market_id"],
        "market_price": selected["market_price"],
        "price_method": selected.get("price_method"),
    }


def selected_rank_by_price(selected_price: float | None, sibling_prices: list[dict[str, Any]]) -> int | None:
    if selected_price is None:
        return None
    price_rows = [("selected_child", selected_price)]
    price_rows.extend(
        (record["child_market_id"], record["market_price"])
        for record in sibling_prices
        if record["market_price"] is not None
    )
    ordered = sorted(price_rows, key=lambda item: (-item[1], item[0]))
    for idx, (child_id, _price) in enumerate(ordered, start=1):
        if child_id == "selected_child":
            return idx
    return None


def exclusive_mass_status(
    *,
    selected_price: float | None,
    known_sibling_price_sum: float,
    missing_sibling_price_count: int,
    family_type: str,
    tolerance: float,
) -> str:
    if family_type != "exclusive":
        return "nonexclusive_family_no_mass_check"
    if selected_price is None or missing_sibling_price_count:
        return "exclusive_price_mass_partial_context"
    total = selected_price + known_sibling_price_sum
    if total > 1.0 + tolerance:
        return "exclusive_price_mass_overfull"
    if total < 1.0 - tolerance:
        return "exclusive_price_mass_underfilled"
    return "exclusive_price_mass_consistent"


def build_family_diagnostics(
    evidence_packet: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic SCAE family diagnostics without moving forecast probability."""

    validate_evidence_packet_family_input(evidence_packet)
    family_policy = family_diagnostics_policy(policy)
    packet = copy.deepcopy(evidence_packet)
    family_context = packet["family_context"]
    family_mode = family_context.get("mode", "unknown")

    base = {
        "artifact_type": SCAE_FAMILY_DIAGNOSTICS_ARTIFACT_TYPE,
        "schema_version": SCAE_FAMILY_DIAGNOSTICS_SCHEMA_VERSION,
        "authority": SCAE_FAMILY_DIAGNOSTICS_AUTHORITY,
        "case_id": packet["case_id"],
        "market_id": packet["market_id"],
        "dispatch_id": packet["dispatch_id"],
        "evidence_packet_ref": packet.get("case_contract_ref"),
        "family_mode": family_mode,
        "source_refs": {
            "family_context": "evidence_packet.family_context",
            "prior_context_seed": "evidence_packet.prior_context_seed",
        },
        "ledger_adjacency": {
            "write_path": "write_scae_family_diagnostics",
            "ledger_role": "diagnostic_sidecar",
            "may_mutate_scae_ledger": False,
            "may_mutate_prior_context": False,
            "may_move_probability": False,
        },
        "no_update_guards": {
            "sibling_price_effect_on_scae_ledger": "none_context_only",
            "probability_movement_authority": "none",
            "softmax_reallocation_applied": False,
            "evidence_update_authorship": "forbidden",
        },
    }

    if family_mode != "family_aware_binary_child":
        diagnostics = {
            **base,
            "diagnostic_status": f"not_applicable_{family_mode}",
            "family_context_summary": {
                "parent_event_id": family_context.get("parent_event_id"),
                "selected_child_market_id": family_context.get("selected_child_market_id"),
                "family_type": family_context.get("family_type"),
                "relation_constraints": list(family_context.get("relation_constraints", []) or []),
            },
            "displacement_signals": {
                "diagnostic_only": True,
                "applicable": False,
                "reason": "not_family_aware_binary_child",
            },
            "consistency_diagnostics": {
                "diagnostic_only": True,
                "diagnostic_flags": [],
                "family_price_mass_status": "not_applicable",
            },
        }
        diagnostics["diagnostic_id"] = stable_id("scae-family-diagnostics", diagnostics)
        validate_family_diagnostics(diagnostics)
        return diagnostics

    for field in ["parent_event_id", "selected_child_market_id", "relation_constraints"]:
        if not family_context.get(field):
            raise ScaeFamilyDiagnosticsError(f"family_context.{field} is required for family-aware diagnostics")

    selected_price = numeric_price(
        packet["prior_context_seed"].get("market_live_probability"),
        "prior_context_seed.market_live_probability",
    )
    sibling_prices, sibling_flags = normalize_sibling_prices(family_context)
    declared_sibling_ids = [
        str(child_id)
        for child_id in family_context.get("sibling_child_ids", [])
        if child_id is not None and child_id != ""
    ]
    priced_sibling_ids = {record["child_market_id"] for record in sibling_prices if record["market_price"] is not None}
    missing_sibling_price_ids = sorted(set(declared_sibling_ids) - priced_sibling_ids)
    known_sibling_prices = [
        record["market_price"]
        for record in sibling_prices
        if record["market_price"] is not None
    ]
    known_sibling_price_sum = sum(known_sibling_prices)
    strongest = strongest_sibling(sibling_prices)
    price_gap_to_strongest = (
        selected_price - strongest["market_price"]
        if selected_price is not None and strongest is not None
        else None
    )
    if selected_price is None or strongest is None:
        sibling_pressure_direction = "missing_selected_or_sibling_price"
    elif strongest["market_price"] > selected_price:
        sibling_pressure_direction = "strongest_sibling_above_selected"
    else:
        sibling_pressure_direction = "selected_at_or_above_siblings"

    family_type = family_context.get("family_type") or "unknown"
    tolerance = float(family_policy["exclusive_family_price_tolerance"])
    family_price_mass_status = exclusive_mass_status(
        selected_price=selected_price,
        known_sibling_price_sum=known_sibling_price_sum,
        missing_sibling_price_count=len(missing_sibling_price_ids),
        family_type=family_type,
        tolerance=tolerance,
    )

    diagnostic_flags = set(sibling_flags)
    diagnostic_flags.update(str(flag) for flag in family_context.get("family_validation_flags", []) if flag)
    if selected_price is None:
        diagnostic_flags.add("selected_child_price_unavailable")
    if missing_sibling_price_ids:
        diagnostic_flags.add("sibling_price_missing_for_declared_child")
    if not sibling_prices:
        diagnostic_flags.add("no_sibling_prices_present")
    if sibling_pressure_direction == "strongest_sibling_above_selected":
        diagnostic_flags.add("sibling_price_above_selected")
    if family_price_mass_status in {"exclusive_price_mass_overfull", "exclusive_price_mass_underfilled"}:
        diagnostic_flags.add(family_price_mass_status)

    diagnostics = {
        **base,
        "diagnostic_status": "emitted",
        "family_context_summary": {
            "parent_event_id": family_context["parent_event_id"],
            "selected_child_market_id": family_context["selected_child_market_id"],
            "family_type": family_type,
            "relation_constraints": list(family_context.get("relation_constraints", []) or []),
            "declared_sibling_child_ids": declared_sibling_ids,
        },
        "sibling_price_context": {
            "diagnostic_only": True,
            "sibling_prices": sibling_prices,
            "known_sibling_price_count": len(known_sibling_prices),
            "missing_sibling_price_ids": missing_sibling_price_ids,
            "sibling_prices_context_only": True,
        },
        "displacement_signals": {
            "diagnostic_only": True,
            "applicable": True,
            "selected_child_market_price": selected_price,
            "known_sibling_price_sum": known_sibling_price_sum,
            "selected_plus_known_sibling_price_sum": (
                selected_price + known_sibling_price_sum if selected_price is not None else None
            ),
            "remainder_after_selected_price": 1.0 - selected_price if selected_price is not None else None,
            "selected_rank_by_market_price": selected_rank_by_price(selected_price, sibling_prices),
            "strongest_sibling": strongest,
            "price_gap_to_strongest_sibling": price_gap_to_strongest,
            "sibling_pressure_direction": sibling_pressure_direction,
        },
        "consistency_diagnostics": {
            "diagnostic_only": True,
            "family_price_mass_status": family_price_mass_status,
            "exclusive_family_price_tolerance": tolerance,
            "diagnostic_flags": sorted(diagnostic_flags),
        },
    }
    diagnostics["diagnostic_id"] = stable_id("scae-family-diagnostics", diagnostics)
    validate_family_diagnostics(diagnostics)
    return diagnostics


def validate_family_diagnostics(diagnostics: dict[str, Any]) -> None:
    if not isinstance(diagnostics, dict):
        raise ScaeFamilyDiagnosticsError("family diagnostics must be an object")
    for field in [
        "artifact_type",
        "schema_version",
        "authority",
        "diagnostic_id",
        "case_id",
        "market_id",
        "dispatch_id",
        "ledger_adjacency",
        "no_update_guards",
        "displacement_signals",
        "consistency_diagnostics",
    ]:
        if field not in diagnostics:
            raise ScaeFamilyDiagnosticsError(f"{field} is required")
    if diagnostics["artifact_type"] != SCAE_FAMILY_DIAGNOSTICS_ARTIFACT_TYPE:
        raise ScaeFamilyDiagnosticsError("artifact_type must be scae_family_diagnostics")
    if diagnostics["schema_version"] != SCAE_FAMILY_DIAGNOSTICS_SCHEMA_VERSION:
        raise ScaeFamilyDiagnosticsError(
            f"schema_version must be {SCAE_FAMILY_DIAGNOSTICS_SCHEMA_VERSION}"
        )
    if diagnostics["authority"] != SCAE_FAMILY_DIAGNOSTICS_AUTHORITY:
        raise ScaeFamilyDiagnosticsError("family diagnostics authority must be diagnostic-only")
    ledger = diagnostics["ledger_adjacency"]
    for field in ["may_mutate_scae_ledger", "may_mutate_prior_context", "may_move_probability"]:
        if ledger.get(field) is not False:
            raise ScaeFamilyDiagnosticsError(f"ledger_adjacency.{field} must be false")
    guards = diagnostics["no_update_guards"]
    if guards.get("sibling_price_effect_on_scae_ledger") != "none_context_only":
        raise ScaeFamilyDiagnosticsError("sibling prices must have no SCAE ledger effect")
    if guards.get("probability_movement_authority") != "none":
        raise ScaeFamilyDiagnosticsError("family diagnostics cannot move probability")
    if guards.get("softmax_reallocation_applied") is not False:
        raise ScaeFamilyDiagnosticsError("family diagnostics cannot apply softmax reallocation")
    if diagnostics["displacement_signals"].get("diagnostic_only") is not True:
        raise ScaeFamilyDiagnosticsError("displacement signals must be diagnostic-only")
    if diagnostics["consistency_diagnostics"].get("diagnostic_only") is not True:
        raise ScaeFamilyDiagnosticsError("consistency diagnostics must be diagnostic-only")
    reject_forbidden_authoring_fields(diagnostics)
