"""Golden fixture registry and fail-closed runner for ADS v2 integration."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ads_handoff import (
    ArtifactManifestContext,
    ArtifactManifestError,
    build_artifact_manifest,
    build_validation_result,
    ensure_artifact_manifest_schema,
    write_artifact_manifest,
    write_validation_result,
)
from .ads_stage_logging import (
    StageContext,
    StageContractError,
    build_pipeline_error_event,
    build_stage_execution_event,
    build_stage_status_snapshot,
    canonical_json,
    command_sha256,
    ensure_stage_logging_schema,
    table_columns,
    utc_now_iso,
    validate_pipeline_error_event,
    validate_transition,
    write_pipeline_error_event,
    write_stage_execution_event,
    write_stage_status_snapshot,
)
from .training_trace import (
    TrainingTraceContext,
    write_session5_minimal_training_trace,
)


GOLDEN_FIXTURE_REGISTRY_TABLE = "golden_fixture_case_registry"
GOLDEN_FIXTURE_RESULTS_TABLE = "golden_fixture_case_results"
GOLDEN_FIXTURE_REGISTRY_SCHEMA_VERSION = "golden-fixture-registry/v1"
GOLDEN_FIXTURE_RESULT_SCHEMA_VERSION = "golden-fixture-case-result/v1"
GOLDEN_FIXTURE_ARTIFACT_SCHEMA_VERSION = "golden-fixture-artifact/v1"
GOLDEN_FIXTURE_HARNESS_VERSION = "golden-fixture-harness/v1"
FIXTURE_RESULT_STATUSES = ("passed", "failed", "blocked")
READY_STATUSES = {"ready_for_integration", "done"}

ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX_PATH = ORCHESTRATOR_ROOT / "plans" / "autonomous-decomposition-swarm-golden-fixture-matrix.md"
DEFAULT_INVENTORY_PATH = ORCHESTRATOR_ROOT / "plans" / "autonomous-decomposition-swarm-feature-inventory.yaml"
FIXTURE_MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "006_golden_fixture_harness.sql"
RUNNER_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "bin" / "run_golden_fixture.py"

STARTER_FIXTURE_IDS = frozenset({"FIX-001", "FIX-002", "FIX-003", "FIX-004", "FIX-005", "FIX-006", "FIX-007"})
FORBIDDEN_PROBABILITY_FIELDS = frozenset(
    {
        "probability",
        "probability_estimate",
        "forecast_probability",
        "forecast_prob",
        "production_forecast_prob",
        "fair_value",
        "interval",
        "confidence_interval",
        "reassembly",
        "decision_recommendation",
        "recommended_decision",
    }
)
DECISION_OVERRIDE_FIELDS = frozenset(
    {
        "probability_override",
        "replacement_probability",
        "production_forecast_prob",
        "upgraded_scae_validity",
        "upgrade_forecast_validity",
        "scae_validity_override",
    }
)


class GoldenFixtureError(ValueError):
    """Raised when a fixture registry or result contract is invalid."""


class FixtureFailClosedError(GoldenFixtureError):
    """Raised when a fixture stage must fail closed and emit an error event."""

    def __init__(
        self,
        *,
        failure_class: str,
        safe_message: str,
        retryability: str = "terminal",
        reason_codes: list[str] | None = None,
        validation_status: str = "invalid_terminal",
        safe_metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.failure_class = failure_class
        self.safe_message = safe_message
        self.retryability = retryability
        self.reason_codes = reason_codes or [failure_class]
        self.validation_status = validation_status
        self.safe_metadata = safe_metadata or {}


@dataclass(frozen=True)
class MatrixFixtureRow:
    fixture_id: str
    stage_gate: str
    owner_sessions: tuple[str, ...]
    scenario: str
    required_assertions: str
    status: str


@dataclass(frozen=True)
class FixtureStageSpec:
    stage: str
    artifact_type: str
    artifact_schema_version: str = GOLDEN_FIXTURE_ARTIFACT_SCHEMA_VERSION
    terminal_status: str = "complete"
    dependency_feature_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)
    forbidden_fields: frozenset[str] = frozenset()
    failure_class: str | None = None
    retryability: str = "terminal"
    expected_missing_artifact: bool = False


@dataclass(frozen=True)
class FixtureSpec:
    fixture_id: str
    stage_gate: str
    owner_sessions: tuple[str, ...]
    scenario: str
    required_assertions: str
    matrix_status: str
    target_feature_ids: tuple[str, ...]
    blocker_ids: tuple[str, ...]
    expected_outcome: str
    starter_implemented: bool
    expected_stages: tuple[FixtureStageSpec, ...] = ()


@dataclass
class FixtureRunResult:
    fixture_result_id: str
    fixture_id: str
    run_id: str
    case_id: str
    case_key: str
    dispatch_id: str
    status: str
    started_at: str
    completed_at: str | None = None
    stage_records: list[dict[str, Any]] = field(default_factory=list)
    artifact_manifest_ids: list[str] = field(default_factory=list)
    validation_result_ids: list[str] = field(default_factory=list)
    error_event_ids: list[str] = field(default_factory=list)
    missing_artifacts: list[str] = field(default_factory=list)
    failure_class: str | None = None
    report_artifact_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


FIXTURE_BLOCKER_REFS = {
    "FIX-001": ("BLK-004", "BLK-012"),
    "FIX-002": ("BLK-025",),
    "FIX-003": ("BLK-014",),
    "FIX-004": ("BLK-015",),
    "FIX-005": ("BLK-016",),
    "FIX-006": ("BLK-001", "BLK-012"),
    "FIX-007": ("BLK-017", "BLK-012"),
    "FIX-008": ("BLK-006",),
    "FIX-009": ("BLK-006",),
    "FIX-010": ("BLK-028",),
    "FIX-011": ("BLK-026",),
    "FIX-012": ("BLK-020",),
    "FIX-013": ("BLK-024",),
    "FIX-014": ("BLK-024",),
    "FIX-015": ("BLK-005",),
    "FIX-016": ("BLK-008",),
    "FIX-017": ("BLK-015",),
    "FIX-018": ("BLK-006",),
    "FIX-019": ("MATURITY-AMRG-REUSE",),
    "FIX-020": ("BLK-006",),
    "FIX-021": ("BLK-009",),
    "FIX-022": ("BLK-020",),
    "FIX-023": ("BLK-021",),
    "FIX-024": ("BLK-010",),
    "FIX-025": ("BLK-006",),
    "FIX-026": ("BLK-022",),
    "FIX-027": ("MATURITY-PROFILE-CANARY",),
    "FIX-028": ("MATURITY-DECOMPOSER-MISS",),
    "FIX-029": ("BLK-004",),
    "FIX-030": ("BLK-012",),
    "FIX-031": ("BLK-027",),
    "FIX-032": ("BLK-028",),
    "FIX-033": ("BLK-028",),
    "FIX-034": ("BLK-028",),
    "FIX-035": ("BLK-029",),
    "FIX-036": ("BLK-029",),
    "FIX-037": ("BLK-030",),
    "FIX-038": ("BLK-031",),
    "FIX-039": ("BLK-032",),
    "FIX-040": ("BLK-033",),
    "FIX-041": ("BLK-034",),
    "FIX-042": ("BLK-027",),
    "FIX-043": ("BLK-035",),
    "FIX-044": ("BLK-036",),
    "FIX-045": ("BLK-037",),
    "FIX-046": ("BLK-038",),
    "FIX-047": ("BLK-039",),
    "FIX-048": ("BLK-037", "BLK-030"),
}

FIXTURE_TARGET_FEATURES = {
    "FIX-001": ("CASE-002", "CTX-001", "POL-003", "AMRG-002", "QDT-002", "RET-001", "CLS-002", "VER-004", "SCAE-001", "SYN-001", "DEC-001"),
    "FIX-002": ("CTX-002", "SCAE-009"),
    "FIX-003": ("AMRG-002", "QDT-001"),
    "FIX-004": ("AMRG-003", "QDT-001", "RET-001"),
    "FIX-005": ("AMRG-008", "QDT-004"),
    "FIX-006": ("CLS-002", "SYN-001", "DEC-001"),
    "FIX-007": ("DEC-001", "SCAE-012", "PERSIST-001"),
    "FIX-008": ("SCAE-002", "SCAE-003"),
    "FIX-009": ("SCAE-002",),
    "FIX-010": ("RET-008", "SCAE-013"),
    "FIX-011": ("RET-005", "CLS-004", "SCAE-013"),
    "FIX-012": ("CLS-002", "VER-001", "VER-002"),
    "FIX-013": ("RET-004", "SCAE-006"),
    "FIX-014": ("RET-004", "SCAE-006"),
    "FIX-015": ("SCAE-005", "SCAE-006"),
    "FIX-016": ("SCAE-007",),
    "FIX-017": ("AMRG-008", "SCAE-010"),
    "FIX-018": ("AMRG-008", "SCAE-002"),
    "FIX-019": ("AMRG-007",),
    "FIX-020": ("SCAE-002", "SCAE-003"),
    "FIX-021": ("RET-005", "SCAE-008"),
    "FIX-022": ("VER-002", "SCAE-004"),
    "FIX-023": ("SCAE-004", "SCAE-012"),
    "FIX-024": ("CAL-001", "SCAE-012"),
    "FIX-025": ("SCAE-002",),
    "FIX-026": ("POL-003", "SCAE-012"),
    "FIX-027": ("CAL-002", "CAL-005"),
    "FIX-028": ("QDT-003", "CAL-004"),
    "FIX-029": ("FND-004",),
    "FIX-030": ("FND-006",),
    "FIX-031": ("QDT-002", "CLS-006", "CLS-008"),
    "FIX-032": ("RET-008", "RET-009"),
    "FIX-033": ("CLS-005", "VER-004"),
    "FIX-034": ("RET-008", "SCAE-013"),
    "FIX-035": ("AMRG-009",),
    "FIX-036": ("AMRG-009",),
    "FIX-037": ("CASE-002", "CTX-001"),
    "FIX-038": ("PERSIST-002", "SCORE-001"),
    "FIX-039": ("FND-005",),
    "FIX-040": ("AUTO-005",),
    "FIX-041": ("AUTO-006",),
    "FIX-042": ("CLS-006",),
    "FIX-043": ("CLS-007", "VER-004"),
    "FIX-044": ("CLS-008",),
    "FIX-045": ("RET-004", "RET-009"),
    "FIX-046": ("RET-010", "RET-009"),
    "FIX-047": ("RET-011", "RET-009"),
    "FIX-048": ("RET-001", "RET-004", "RET-009"),
}


def stable_id(prefix: str, *parts: object) -> str:
    seed = "|".join(str(part) for part in parts)
    return prefix + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def parse_owner_sessions(raw: str) -> tuple[str, ...]:
    sessions: list[str] = []
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            sessions.extend(f"Session {idx}" for idx in range(int(start), int(end) + 1))
        else:
            sessions.append(f"Session {int(part)}")
    return tuple(sessions)


def parse_fixture_matrix(path: Path = DEFAULT_MATRIX_PATH) -> dict[str, MatrixFixtureRow]:
    rows: dict[str, MatrixFixtureRow] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| FIX-"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 6:
            raise GoldenFixtureError(f"fixture matrix row must have 6 cells: {line}")
        fixture_id, stage_gate, owner_sessions, scenario, required_assertions, status = cells
        rows[fixture_id] = MatrixFixtureRow(
            fixture_id=fixture_id,
            stage_gate=stage_gate,
            owner_sessions=parse_owner_sessions(owner_sessions),
            scenario=scenario,
            required_assertions=required_assertions,
            status=status,
        )
    if not rows:
        raise GoldenFixtureError(f"no fixture rows found in {path}")
    return rows


def _stage(
    stage: str,
    artifact_type: str,
    *features: str,
    terminal_status: str = "complete",
    reason_codes: tuple[str, ...] = (),
    payload: dict[str, Any] | None = None,
    forbidden_fields: frozenset[str] = frozenset(),
    failure_class: str | None = None,
    retryability: str = "terminal",
) -> FixtureStageSpec:
    return FixtureStageSpec(
        stage=stage,
        artifact_type=artifact_type,
        terminal_status=terminal_status,
        dependency_feature_ids=tuple(features),
        reason_codes=reason_codes,
        payload=payload or {},
        forbidden_fields=forbidden_fields,
        failure_class=failure_class,
        retryability=retryability,
    )


def starter_stage_specs() -> dict[str, tuple[FixtureStageSpec, ...]]:
    common_prefix = (
        _stage("case_selection", "ads-case-contract-fixture", "CASE-002"),
        _stage("evidence_packet", "evidence-packet-fixture", "CTX-001"),
        _stage("policy_context", "effective-profile-fixture", "POL-003"),
    )
    common_forecast_path = (
        _stage("decomposition", "question-decomposition-fixture", "QDT-002"),
        _stage("retrieval", "retrieval-packet-fixture", "RET-001"),
        _stage("researcher_classification", "researcher-sidecar-fixture", "CLS-002"),
        _stage("classification_verification", "verification-slice-fixture", "VER-004"),
        _stage("scae", "scae-ledger-fixture", "SCAE-001", payload={"scae_only_probability_authority": True}),
        _stage("synthesis", "synthesis-context-fixture", "SYN-001", payload={"probability_authority": "scae_only"}),
        _stage("decision", "decision-context-fixture", "DEC-001", payload={"decision_authority": "downgrade_only"}),
        _stage("terminal", "fixture-terminal-fixture", "FND-005"),
    )
    return {
        "FIX-001": common_prefix
        + (
            _stage("related_market_context", "no-related-context-waiver-fixture", "AMRG-002", terminal_status="waived", reason_codes=("standalone_binary_market",)),
        )
        + common_forecast_path,
        "FIX-002": common_prefix
        + (
            _stage(
                "related_market_context",
                "family-aware-context-fixture",
                "CTX-002",
                payload={"selected_child_remains_binary": True, "sibling_prices_context_only": True, "sibling_evidence_delta": None},
            ),
        )
        + common_forecast_path,
        "FIX-003": common_prefix
        + (
            _stage(
                "related_market_context",
                "amrg-no-related-context-waiver-fixture",
                "AMRG-002",
                terminal_status="waived",
                reason_codes=("empty_active_safe_candidate_pool", "explicit_waiver_written"),
                payload={"candidate_pool_size": 0, "decomposition_may_proceed": True},
            ),
            _stage("decomposition", "question-decomposition-fixture", "QDT-001", payload={"consumed_no_related_context_waiver": True}),
            _stage("terminal", "fixture-terminal-fixture", "FND-005"),
        ),
        "FIX-004": common_prefix
        + (
            _stage(
                "related_market_context",
                "weak-context-amrg-fixture",
                "AMRG-003",
                payload={"edge_status": "weak_context_only", "allowed_effects": ["decomposition_hint", "retrieval_hint"], "promotion_allowed": False},
            ),
            _stage("decomposition", "question-decomposition-fixture", "QDT-001", payload={"weak_context_only_refs": ["artifact:weak-context-amrg"]}),
            _stage("retrieval", "retrieval-packet-fixture", "RET-001", payload={"amrg_effects": ["hint_only"]}),
            _stage("terminal", "fixture-terminal-fixture", "FND-005"),
        ),
        "FIX-005": common_prefix
        + (
            _stage(
                "related_market_context",
                "conditional-anchor-negative-fixture",
                "AMRG-008",
                payload={"strict_precedence_candidate": "failed_validation", "fallback_policy": "repair_then_exhaust"},
            ),
            _stage(
                "decomposition",
                "qdt-anchor-validation-fixture",
                "QDT-004",
                payload={"repair_attempted": True, "repair_exhausted": True},
                failure_class="amrg_anchor_required_unrepairable",
                retryability="terminal",
            ),
        ),
        "FIX-006": common_prefix
        + (
            _stage("related_market_context", "no-related-context-waiver-fixture", "AMRG-002", terminal_status="waived"),
            _stage("decomposition", "question-decomposition-fixture", "QDT-002"),
            _stage("retrieval", "retrieval-packet-fixture", "RET-001"),
            _stage(
                "researcher_classification",
                "researcher-sidecar-fixture",
                "CLS-002",
                payload={"classification": "supports_yes", "probability": 0.61, "fair_value": 0.59, "interval": [0.51, 0.71]},
                forbidden_fields=FORBIDDEN_PROBABILITY_FIELDS,
                failure_class="forbidden_probability_field",
            ),
        ),
        "FIX-007": common_prefix
        + (
            _stage("related_market_context", "no-related-context-waiver-fixture", "AMRG-002", terminal_status="waived"),
        )
        + common_forecast_path[:-3]
        + (
            _stage("synthesis", "synthesis-context-fixture", "SYN-001", payload={"probability_authority": "scae_only"}),
            _stage(
                "decision",
                "decision-context-fixture",
                "DEC-001",
                payload={"actionability": "execute", "probability_override": 0.72, "upgraded_scae_validity": True},
                forbidden_fields=DECISION_OVERRIDE_FIELDS,
                failure_class="decision_probability_override_attempt",
            ),
        ),
    }


def build_fixture_registry(path: Path = DEFAULT_MATRIX_PATH) -> dict[str, FixtureSpec]:
    rows = parse_fixture_matrix(path)
    starters = starter_stage_specs()
    registry: dict[str, FixtureSpec] = {}
    for fixture_id, row in rows.items():
        stage_specs = starters.get(fixture_id, ())
        registry[fixture_id] = FixtureSpec(
            fixture_id=fixture_id,
            stage_gate=row.stage_gate,
            owner_sessions=row.owner_sessions,
            scenario=row.scenario,
            required_assertions=row.required_assertions,
            matrix_status=row.status,
            target_feature_ids=FIXTURE_TARGET_FEATURES.get(fixture_id, ("FND-005",)),
            blocker_ids=FIXTURE_BLOCKER_REFS.get(fixture_id, ("BLK-UNMAPPED",)),
            expected_outcome=row.required_assertions,
            starter_implemented=fixture_id in STARTER_FIXTURE_IDS,
            expected_stages=stage_specs,
        )
    validate_fixture_registry(registry)
    return registry


def validate_fixture_registry(registry: dict[str, FixtureSpec]) -> None:
    if not registry:
        raise GoldenFixtureError("fixture registry is empty")
    for fixture_id, spec in registry.items():
        if not re.fullmatch(r"FIX-\d{3}", fixture_id):
            raise GoldenFixtureError(f"invalid fixture_id: {fixture_id}")
        if not spec.owner_sessions:
            raise GoldenFixtureError(f"{fixture_id}: owner_sessions required")
        if not spec.target_feature_ids:
            raise GoldenFixtureError(f"{fixture_id}: target_feature_ids required")
        if not spec.blocker_ids:
            raise GoldenFixtureError(f"{fixture_id}: blocker_ids required")
        if not spec.expected_outcome:
            raise GoldenFixtureError(f"{fixture_id}: expected_outcome required")
        if not spec.matrix_status:
            raise GoldenFixtureError(f"{fixture_id}: matrix status required")
        if spec.starter_implemented and not spec.expected_stages:
            raise GoldenFixtureError(f"{fixture_id}: starter fixture missing expected stages")


def load_inventory_statuses(path: Path = DEFAULT_INVENTORY_PATH) -> dict[str, str]:
    inventory = json.loads(path.read_text(encoding="utf-8"))
    statuses: dict[str, str] = {}
    for row in inventory.get("features", []):
        statuses[row["id"]] = row["status"]
    for row in inventory.get("migrations", []):
        statuses[row["id"]] = row["status"]
    return statuses


def ensure_golden_fixture_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(FIXTURE_MIGRATION.read_text(encoding="utf-8"))
    compat_columns = {
        GOLDEN_FIXTURE_REGISTRY_TABLE: {
            "fixture_id": "TEXT",
            "schema_version": "TEXT",
            "stage_gate": "TEXT",
            "owner_sessions": "TEXT NOT NULL DEFAULT '[]'",
            "scenario": "TEXT",
            "required_assertions": "TEXT",
            "matrix_status": "TEXT",
            "target_feature_ids": "TEXT NOT NULL DEFAULT '[]'",
            "blocker_ids": "TEXT NOT NULL DEFAULT '[]'",
            "expected_outcome": "TEXT",
            "expected_stages": "TEXT NOT NULL DEFAULT '[]'",
            "starter_implemented": "INTEGER NOT NULL DEFAULT 0",
            "metadata": "TEXT NOT NULL DEFAULT '{}'",
            "updated_at": "TEXT",
        },
        GOLDEN_FIXTURE_RESULTS_TABLE: {
            "fixture_result_id": "TEXT",
            "schema_version": "TEXT",
            "fixture_id": "TEXT",
            "run_id": "TEXT",
            "case_id": "TEXT",
            "case_key": "TEXT",
            "dispatch_id": "TEXT",
            "status": "TEXT",
            "started_at": "TEXT",
            "completed_at": "TEXT",
            "stage_records": "TEXT NOT NULL DEFAULT '[]'",
            "artifact_manifest_ids": "TEXT NOT NULL DEFAULT '[]'",
            "validation_result_ids": "TEXT NOT NULL DEFAULT '[]'",
            "error_event_ids": "TEXT NOT NULL DEFAULT '[]'",
            "missing_artifacts": "TEXT NOT NULL DEFAULT '[]'",
            "failure_class": "TEXT",
            "report_artifact_id": "TEXT",
            "metadata": "TEXT NOT NULL DEFAULT '{}'",
            "updated_at": "TEXT",
        },
    }
    for table, columns in compat_columns.items():
        existing = table_columns(conn, table)
        for column, definition in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        if table == GOLDEN_FIXTURE_REGISTRY_TABLE:
            conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_golden_fixture_registry_fixture_id ON {table}(fixture_id)")
        else:
            conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_golden_fixture_results_result_id ON {table}(fixture_result_id)")


def write_fixture_registry(conn: sqlite3.Connection, registry: dict[str, FixtureSpec]) -> None:
    validate_fixture_registry(registry)
    ensure_golden_fixture_schema(conn)
    for spec in registry.values():
        conn.execute(
            f"""
            INSERT INTO {GOLDEN_FIXTURE_REGISTRY_TABLE} (
              fixture_id, schema_version, case_key, title, stage_gate,
              owner_sessions, scenario, required_assertions, matrix_status,
              target_feature_ids, blocker_ids, expected_outcome,
              expected_stages, starter_implemented, metadata, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(fixture_id) DO UPDATE SET
              schema_version=excluded.schema_version,
              title=excluded.title,
              stage_gate=excluded.stage_gate,
              owner_sessions=excluded.owner_sessions,
              scenario=excluded.scenario,
              required_assertions=excluded.required_assertions,
              matrix_status=excluded.matrix_status,
              target_feature_ids=excluded.target_feature_ids,
              blocker_ids=excluded.blocker_ids,
              expected_outcome=excluded.expected_outcome,
              expected_stages=excluded.expected_stages,
              starter_implemented=excluded.starter_implemented,
              metadata=excluded.metadata,
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                spec.fixture_id,
                GOLDEN_FIXTURE_REGISTRY_SCHEMA_VERSION,
                f"golden-fixture:{spec.fixture_id}",
                spec.scenario,
                spec.stage_gate,
                canonical_json(list(spec.owner_sessions)),
                spec.scenario,
                spec.required_assertions,
                spec.matrix_status,
                canonical_json(list(spec.target_feature_ids)),
                canonical_json(list(spec.blocker_ids)),
                spec.expected_outcome,
                canonical_json([stage.stage for stage in spec.expected_stages]),
                1 if spec.starter_implemented else 0,
                canonical_json({"harness_version": GOLDEN_FIXTURE_HARNESS_VERSION}),
            ),
        )


def write_fixture_result(conn: sqlite3.Connection, result: FixtureRunResult) -> str:
    validate_fixture_result(result)
    ensure_golden_fixture_schema(conn)
    conn.execute(
        f"""
        INSERT INTO {GOLDEN_FIXTURE_RESULTS_TABLE} (
          fixture_result_id, schema_version, fixture_id, run_id, case_id,
          case_key, dispatch_id, status, started_at, completed_at,
          stage_records, artifact_manifest_ids, validation_result_ids,
          error_event_ids, missing_artifacts, failure_class, report_artifact_id,
          metadata, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(fixture_result_id) DO UPDATE SET
          status=excluded.status,
          completed_at=excluded.completed_at,
          stage_records=excluded.stage_records,
          artifact_manifest_ids=excluded.artifact_manifest_ids,
          validation_result_ids=excluded.validation_result_ids,
          error_event_ids=excluded.error_event_ids,
          missing_artifacts=excluded.missing_artifacts,
          failure_class=excluded.failure_class,
          report_artifact_id=excluded.report_artifact_id,
          metadata=excluded.metadata,
          updated_at=CURRENT_TIMESTAMP
        """,
        (
            result.fixture_result_id,
            GOLDEN_FIXTURE_RESULT_SCHEMA_VERSION,
            result.fixture_id,
            result.run_id,
            result.case_id,
            result.case_key,
            result.dispatch_id,
            result.status,
            result.started_at,
            result.completed_at,
            canonical_json(result.stage_records),
            canonical_json(result.artifact_manifest_ids),
            canonical_json(result.validation_result_ids),
            canonical_json(result.error_event_ids),
            canonical_json(result.missing_artifacts),
            result.failure_class,
            result.report_artifact_id,
            canonical_json(result.metadata),
        ),
    )
    return result.fixture_result_id


def validate_fixture_result(result: FixtureRunResult) -> None:
    if result.status not in FIXTURE_RESULT_STATUSES:
        raise GoldenFixtureError(f"unknown fixture result status: {result.status}")
    for field_name in ("fixture_result_id", "fixture_id", "run_id", "case_id", "case_key", "dispatch_id", "started_at"):
        if not getattr(result, field_name):
            raise GoldenFixtureError(f"{field_name} is required")


def find_forbidden_fields(value: Any, forbidden_fields: frozenset[str], path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in forbidden_fields:
                hits.append(child_path)
            hits.extend(find_forbidden_fields(child, forbidden_fields, child_path))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            hits.extend(find_forbidden_fields(child, forbidden_fields, f"{path}[{idx}]"))
    return hits


def validate_fixture_artifact_payload(spec: FixtureSpec, stage: FixtureStageSpec, payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != stage.artifact_schema_version:
        raise FixtureFailClosedError(
            failure_class="schema_validation_failed",
            safe_message=f"{stage.stage} fixture artifact has invalid schema_version",
            reason_codes=["fixture_artifact_schema_mismatch"],
            safe_metadata={"expected_schema_version": stage.artifact_schema_version, "actual_schema_version": payload.get("schema_version")},
        )
    if payload.get("fixture_id") != spec.fixture_id or payload.get("stage") != stage.stage:
        raise FixtureFailClosedError(
            failure_class="schema_validation_failed",
            safe_message=f"{stage.stage} fixture artifact identity does not match the stage",
            reason_codes=["fixture_artifact_identity_mismatch"],
        )
    if stage.forbidden_fields:
        hits = find_forbidden_fields(payload, stage.forbidden_fields)
        if hits:
            raise FixtureFailClosedError(
                failure_class=stage.failure_class or "forbidden_probability_field",
                safe_message=f"{stage.stage} fixture artifact contains forbidden authority fields",
                reason_codes=["forbidden_authority_field"],
                safe_metadata={"forbidden_field_paths": hits[:10]},
            )
    if stage.failure_class:
        raise FixtureFailClosedError(
            failure_class=stage.failure_class,
            safe_message=f"{stage.stage} fixture records expected fail-closed condition",
            reason_codes=list(stage.reason_codes or (stage.failure_class,)),
            retryability=stage.retryability,
            safe_metadata={"fixture_id": spec.fixture_id, "stage": stage.stage},
        )


def artifact_payload(spec: FixtureSpec, stage: FixtureStageSpec, result: FixtureRunResult) -> dict[str, Any]:
    return {
        "schema_version": stage.artifact_schema_version,
        "fixture_id": spec.fixture_id,
        "case_id": result.case_id,
        "case_key": result.case_key,
        "dispatch_id": result.dispatch_id,
        "stage": stage.stage,
        "artifact_type": stage.artifact_type,
        "stub_only": True,
        "no_live_execution": True,
        "assertion": spec.required_assertions,
        "payload": stage.payload,
    }


def artifact_context(result: FixtureRunResult, stage: FixtureStageSpec, stage_attempt_id: str) -> ArtifactManifestContext:
    return ArtifactManifestContext(
        case_id=result.case_id,
        case_key=result.case_key,
        dispatch_id=result.dispatch_id,
        stage=stage.stage,
        stage_attempt_id=stage_attempt_id,
        pipeline_run_id=result.run_id,
        producer="orchestrator-golden-fixture-harness",
        forecast_timestamp=result.started_at,
        source_cutoff_timestamp=result.started_at,
        generated_at=utc_now_iso(),
    )


def stage_context(result: FixtureRunResult, stage: FixtureStageSpec, stage_attempt_id: str) -> StageContext:
    return StageContext(
        case_id=result.case_id,
        case_key=result.case_key,
        dispatch_id=result.dispatch_id,
        stage=stage.stage,
        stage_attempt_id=stage_attempt_id,
        pipeline_run_id=result.run_id,
        case_lease_id=f"fixture-lease:{result.run_id}",
    )


def replay_command(result: FixtureRunResult, stage: FixtureStageSpec) -> str:
    return f"python3 {RUNNER_SCRIPT_PATH} --fixture-id {result.fixture_id} --run-id {result.run_id} --stage {stage.stage}"


def write_status(
    conn: sqlite3.Connection,
    *,
    result: FixtureRunResult,
    context: StageContext,
    status: str,
    replay: str,
    input_artifacts: list[str] | None = None,
    output_artifacts: list[str] | None = None,
    dependency_feature_ids: tuple[str, ...] = (),
    blocking_feature_ids: list[str] | None = None,
    reason_codes: list[str] | None = None,
    latest_execution_event_ids: list[str] | None = None,
    error_event_ids: list[str] | None = None,
) -> None:
    record = build_stage_status_snapshot(
        context=context,
        status=status,
        started_at=result.started_at,
        completed_at=utc_now_iso() if status != "running" else None,
        input_artifacts=input_artifacts or [],
        output_artifacts=output_artifacts or [],
        dependency_feature_ids=dependency_feature_ids,
        blocking_feature_ids=blocking_feature_ids or [],
        reason_codes=reason_codes or [],
        latest_execution_event_ids=latest_execution_event_ids or [],
        error_event_ids=error_event_ids or [],
        replay_command=replay,
        metadata={"fixture_id": result.fixture_id, "fixture_result_id": result.fixture_result_id},
    )
    write_stage_status_snapshot(conn, record)
    result.stage_records.append(
        {
            "stage": context.stage,
            "status": status,
            "stage_attempt_id": context.stage_attempt_id,
            "execution_event_ids": latest_execution_event_ids or [],
            "error_event_ids": error_event_ids or [],
            "reason_codes": reason_codes or [],
        }
    )


def build_and_write_event(
    conn: sqlite3.Connection,
    *,
    result: FixtureRunResult,
    context: StageContext,
    stage: FixtureStageSpec,
    event_suffix: str,
    event_type: str,
    event_status: str,
    replay: str,
    input_artifact_refs: list[str] | None = None,
    output_artifact_refs: list[str] | None = None,
    validation_result_refs: list[str] | None = None,
    error_event_id: str | None = None,
    failure_class: str | None = None,
    safe_exception_class: str | None = None,
    safe_exception_message: str | None = None,
) -> str:
    event = build_stage_execution_event(
        execution_event_id=stable_id("stage-exec-event:", result.run_id, stage.stage, event_suffix),
        context=context,
        event_type=event_type,
        event_status=event_status,
        attempt_number=1,
        max_attempts=1,
        runner_ref="ads-golden-fixture-runner",
        agent_or_component_ref="orchestrator",
        script_path=str(RUNNER_SCRIPT_PATH),
        command_sha256_value=command_sha256(replay),
        input_artifact_refs=input_artifact_refs or [],
        output_artifact_refs=output_artifact_refs or [],
        validation_result_refs=validation_result_refs or [],
        error_event_id=error_event_id,
        failure_class=failure_class,
        safe_exception_class=safe_exception_class,
        safe_exception_message=safe_exception_message,
        no_log_reason="fixture stub stage; no live component log emitted",
        redaction_status="not_needed",
        replay_command=replay,
        safe_metadata={"fixture_id": result.fixture_id, "fixture_result_id": result.fixture_result_id},
    )
    return write_stage_execution_event(conn, event)


def dependency_failures(stage: FixtureStageSpec, dependency_mode: str, inventory_statuses: dict[str, str]) -> list[str]:
    if dependency_mode == "fixture":
        return []
    failures: list[str] = []
    for feature_id in stage.dependency_feature_ids:
        if inventory_statuses.get(feature_id) not in READY_STATUSES:
            failures.append(feature_id)
    return failures


def write_fail_closed(
    conn: sqlite3.Connection,
    *,
    result: FixtureRunResult,
    context: StageContext,
    stage: FixtureStageSpec,
    failure: FixtureFailClosedError,
    replay: str,
    validation_result_refs: list[str] | None = None,
    output_artifact_refs: list[str] | None = None,
) -> None:
    failed_event_id = stable_id("stage-exec-event:", result.run_id, stage.stage, "failed")
    error_event_id = stable_id("pipeline-error:", result.run_id, stage.stage, failure.failure_class)
    grouping_key = f"{stage.stage}:{failure.failure_class}:{':'.join(failure.reason_codes)}"
    error_record = build_pipeline_error_event(
        error_event_id=error_event_id,
        execution_event_id=failed_event_id,
        context=context,
        failure_class=failure.failure_class,
        failure_grouping_key=grouping_key,
        retryability=failure.retryability,
        safe_message=failure.safe_message,
        safe_metadata=failure.safe_metadata,
        replay_command=replay,
        bounded_log_artifact_refs=[],
    )
    validate_pipeline_error_event(error_record)
    write_pipeline_error_event(conn, error_record)
    failed_event = build_stage_execution_event(
        execution_event_id=failed_event_id,
        context=context,
        event_type="stage_blocked" if failure.retryability == "blocked" else "artifact_validation_failed",
        event_status="warning" if failure.retryability == "blocked" else "error",
        attempt_number=1,
        max_attempts=1,
        runner_ref="ads-golden-fixture-runner",
        agent_or_component_ref="orchestrator",
        script_path=str(RUNNER_SCRIPT_PATH),
        command_sha256_value=command_sha256(replay),
        output_artifact_refs=output_artifact_refs or [],
        validation_result_refs=validation_result_refs or [],
        error_event_id=error_event_id,
        failure_class=failure.failure_class,
        safe_exception_class=type(failure).__name__,
        safe_exception_message=failure.safe_message,
        no_log_reason="fixture fail-closed condition; no live component log emitted",
        redaction_status="not_needed",
        replay_command=replay,
        safe_metadata={"fixture_id": result.fixture_id, "reason_codes": failure.reason_codes},
    )
    write_stage_execution_event(conn, failed_event)
    result.error_event_ids.append(error_event_id)
    result.failure_class = failure.failure_class
    expected_fail_closed = stage.failure_class == failure.failure_class
    if not expected_fail_closed:
        result.status = "blocked" if failure.retryability == "blocked" else "failed"
    write_status(
        conn,
        result=result,
        context=context,
        status="blocked" if failure.retryability == "blocked" else "failed",
        replay=replay,
        output_artifacts=output_artifact_refs or [],
        dependency_feature_ids=stage.dependency_feature_ids,
        blocking_feature_ids=failure.safe_metadata.get("blocking_feature_ids", []),
        reason_codes=failure.reason_codes,
        latest_execution_event_ids=[failed_event_id],
        error_event_ids=[error_event_id],
    )


def run_fixture_stage(
    conn: sqlite3.Connection,
    *,
    spec: FixtureSpec,
    result: FixtureRunResult,
    stage: FixtureStageSpec,
    output_dir: Path,
    dependency_mode: str,
    inventory_statuses: dict[str, str],
    simulate_missing_artifact_stage: str | None = None,
    force_invalid_transition_stage: str | None = None,
) -> bool:
    stage_attempt_id = stable_id("stage-attempt:", result.run_id, stage.stage)
    context = stage_context(result, stage, stage_attempt_id)
    replay = replay_command(result, stage)
    blocked_features = dependency_failures(stage, dependency_mode, inventory_statuses)
    if blocked_features:
        write_fail_closed(
            conn,
            result=result,
            context=context,
            stage=stage,
            replay=replay,
            failure=FixtureFailClosedError(
                failure_class="dependency_not_ready",
                safe_message=f"{stage.stage} dependencies are not ready for runtime integration",
                retryability="blocked",
                reason_codes=["dependency_not_ready"],
                safe_metadata={"blocking_feature_ids": blocked_features},
            ),
        )
        return False

    started_event_id = build_and_write_event(
        conn,
        result=result,
        context=context,
        stage=stage,
        event_suffix="started",
        event_type="stage_started",
        event_status="info",
        replay=replay,
    )
    try:
        if force_invalid_transition_stage == stage.stage:
            validate_transition("not_started", stage.terminal_status)
        elif stage.terminal_status == "waived":
            validate_transition("not_started", "waived")
        else:
            validate_transition("not_started", "running")
            write_status(
                conn,
                result=result,
                context=context,
                status="running",
                replay=replay,
                dependency_feature_ids=stage.dependency_feature_ids,
                latest_execution_event_ids=[started_event_id],
            )

        payload = artifact_payload(spec, stage, result)
        artifact_path = output_dir / f"{spec.fixture_id}-{stage.stage}.json"
        artifact_path.write_text(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        if simulate_missing_artifact_stage == stage.stage:
            artifact_path.unlink()
        try:
            manifest = build_artifact_manifest(
                context=artifact_context(result, stage, stage_attempt_id),
                artifact_type=stage.artifact_type,
                artifact_schema_version=stage.artifact_schema_version,
                path=artifact_path,
                validation_status="not_validated",
                validator_version=GOLDEN_FIXTURE_HARNESS_VERSION,
                temporal_isolation_status="not_applicable",
                metadata={"fixture_id": spec.fixture_id, "stub_only": True},
            )
        except ArtifactManifestError as exc:
            if "missing" in str(exc):
                result.missing_artifacts.append(str(artifact_path))
                raise FixtureFailClosedError(
                    failure_class="missing_required_artifact",
                    safe_message=f"{stage.stage} fixture artifact is missing",
                    reason_codes=["missing_required_artifact"],
                    safe_metadata={"artifact_path": str(artifact_path)},
                ) from exc
            raise FixtureFailClosedError(
                failure_class="schema_validation_failed",
                safe_message=f"{stage.stage} fixture artifact manifest failed validation",
                reason_codes=["artifact_manifest_validation_failed"],
                safe_metadata={"error": str(exc)},
            ) from exc

        artifact_id = write_artifact_manifest(conn, manifest)
        result.artifact_manifest_ids.append(artifact_id)
        validation_status = "valid"
        validation_messages = ["fixture artifact validated"]
        try:
            validate_fixture_artifact_payload(spec, stage, payload)
        except FixtureFailClosedError as exc:
            validation_status = exc.validation_status
            validation_messages = [exc.safe_message]
            validation = build_validation_result(
                artifact_id=artifact_id,
                status=validation_status,
                validator_version=GOLDEN_FIXTURE_HARNESS_VERSION,
                reason_codes=exc.reason_codes,
                validation_messages=validation_messages,
                metadata={"fixture_id": spec.fixture_id, "stage": stage.stage},
                validation_result_id=stable_id("artifact-validation:", result.run_id, stage.stage, validation_status),
            )
            validation_result_id = write_validation_result(conn, validation)
            result.validation_result_ids.append(validation_result_id)
            manifest = dict(manifest)
            manifest["validation_status"] = validation_status
            manifest["validation_result_refs"] = [validation_result_id]
            write_artifact_manifest(conn, manifest)
            write_fail_closed(
                conn,
                result=result,
                context=context,
                stage=stage,
                failure=exc,
                replay=replay,
                validation_result_refs=[validation_result_id],
                output_artifact_refs=[artifact_id],
            )
            return False

        validation = build_validation_result(
            artifact_id=artifact_id,
            status=validation_status,
            validator_version=GOLDEN_FIXTURE_HARNESS_VERSION,
            reason_codes=["fixture_artifact_valid"],
            validation_messages=validation_messages,
            metadata={"fixture_id": spec.fixture_id, "stage": stage.stage},
            validation_result_id=stable_id("artifact-validation:", result.run_id, stage.stage, validation_status),
        )
        validation_result_id = write_validation_result(conn, validation)
        result.validation_result_ids.append(validation_result_id)
        manifest = dict(manifest)
        manifest["validation_status"] = validation_status
        manifest["validation_result_refs"] = [validation_result_id]
        write_artifact_manifest(conn, manifest)

        if stage.terminal_status != "waived":
            validate_transition("running", stage.terminal_status)
        completed_event_id = build_and_write_event(
            conn,
            result=result,
            context=context,
            stage=stage,
            event_suffix="completed",
            event_type="stage_completed",
            event_status="info",
            replay=replay,
            output_artifact_refs=[artifact_id],
            validation_result_refs=[validation_result_id],
        )
        write_status(
            conn,
            result=result,
            context=context,
            status=stage.terminal_status,
            replay=replay,
            output_artifacts=[artifact_id],
            dependency_feature_ids=stage.dependency_feature_ids,
            reason_codes=list(stage.reason_codes),
            latest_execution_event_ids=[completed_event_id],
        )
        return True
    except StageContractError as exc:
        write_fail_closed(
            conn,
            result=result,
            context=context,
            stage=stage,
            replay=replay,
            failure=FixtureFailClosedError(
                failure_class="invalid_stage_transition",
                safe_message=f"{stage.stage} attempted an invalid fixture status transition",
                reason_codes=["invalid_stage_transition"],
                safe_metadata={"error": str(exc)},
            ),
        )
        return False
    except FixtureFailClosedError as exc:
        write_fail_closed(
            conn,
            result=result,
            context=context,
            stage=stage,
            replay=replay,
            failure=exc,
        )
        return False


def result_report_payload(result: FixtureRunResult) -> dict[str, Any]:
    return {
        "schema_version": GOLDEN_FIXTURE_RESULT_SCHEMA_VERSION,
        "fixture_result_id": result.fixture_result_id,
        "fixture_id": result.fixture_id,
        "run_id": result.run_id,
        "case_id": result.case_id,
        "case_key": result.case_key,
        "dispatch_id": result.dispatch_id,
        "status": result.status,
        "started_at": result.started_at,
        "completed_at": result.completed_at,
        "stage_records": result.stage_records,
        "artifact_manifest_ids": result.artifact_manifest_ids,
        "validation_result_ids": result.validation_result_ids,
        "error_event_ids": result.error_event_ids,
        "missing_artifacts": result.missing_artifacts,
        "failure_class": result.failure_class,
        "metadata": result.metadata,
    }


def write_result_report_artifact(conn: sqlite3.Connection, result: FixtureRunResult, output_dir: Path) -> str:
    terminal_stage = FixtureStageSpec(stage="terminal", artifact_type="golden-fixture-result-report")
    stage_attempt_id = stable_id("stage-attempt:", result.run_id, "terminal-report")
    report_path = output_dir / f"{result.fixture_id}-result-report.json"
    report_path.write_text(json.dumps(result_report_payload(result), sort_keys=True, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    manifest = build_artifact_manifest(
        context=artifact_context(result, terminal_stage, stage_attempt_id),
        artifact_type="golden-fixture-result-report",
        artifact_schema_version=GOLDEN_FIXTURE_RESULT_SCHEMA_VERSION,
        path=report_path,
        validation_status="valid",
        validator_version=GOLDEN_FIXTURE_HARNESS_VERSION,
        temporal_isolation_status="not_applicable",
        metadata={"fixture_id": result.fixture_id, "result_status": result.status},
    )
    artifact_id = write_artifact_manifest(conn, manifest)
    validation = build_validation_result(
        artifact_id=artifact_id,
        status="valid",
        validator_version=GOLDEN_FIXTURE_HARNESS_VERSION,
        reason_codes=["fixture_result_report_valid"],
        validation_messages=["fixture result report persisted"],
        metadata={"fixture_id": result.fixture_id},
        validation_result_id=stable_id("artifact-validation:", result.run_id, "terminal-report", "valid"),
    )
    validation_result_id = write_validation_result(conn, validation)
    result.validation_result_ids.append(validation_result_id)
    result.artifact_manifest_ids.append(artifact_id)
    manifest = dict(manifest)
    manifest["validation_result_refs"] = [validation_result_id]
    write_artifact_manifest(conn, manifest)
    result.report_artifact_id = artifact_id
    return artifact_id


def artifact_manifest_refs_for_trace(conn: sqlite3.Connection, result: FixtureRunResult) -> list[dict[str, str]]:
    if not result.artifact_manifest_ids:
        raise GoldenFixtureError(f"{result.fixture_id}: training trace requires artifact manifest IDs")
    placeholders = ", ".join("?" for _ in result.artifact_manifest_ids)
    rows = conn.execute(
        f"""
        SELECT artifact_id, artifact_sha256, stage, artifact_type
        FROM case_artifact_manifest
        WHERE artifact_id IN ({placeholders})
        """,
        tuple(result.artifact_manifest_ids),
    ).fetchall()
    manifests_by_id = {
        artifact_id: {"artifact_id": artifact_id, "sha256": artifact_sha256, "stage": stage, "artifact_type": artifact_type}
        for artifact_id, artifact_sha256, stage, artifact_type in rows
    }
    hashes_by_id = {artifact_id: manifest["sha256"] for artifact_id, manifest in manifests_by_id.items()}
    missing = [artifact_id for artifact_id in result.artifact_manifest_ids if artifact_id not in hashes_by_id]
    if missing:
        raise GoldenFixtureError(f"{result.fixture_id}: missing artifact hashes for trace pointer: {missing}")
    return [manifests_by_id[artifact_id] for artifact_id in result.artifact_manifest_ids]


def write_fixture_training_trace_pointer(conn: sqlite3.Connection, result: FixtureRunResult) -> str | None:
    if result.fixture_id != "FIX-001" or result.status != "passed":
        return None
    trace_id = write_session5_minimal_training_trace(
        conn,
        context=TrainingTraceContext(
            case_id=result.case_id,
            case_key=result.case_key,
            dispatch_id=result.dispatch_id,
            run_id=result.run_id,
            forecast_timestamp=result.started_at,
        ),
        artifact_manifests=artifact_manifest_refs_for_trace(conn, result),
        metadata={
            "fixture_id": result.fixture_id,
            "fixture_result_id": result.fixture_result_id,
            "harness_version": GOLDEN_FIXTURE_HARNESS_VERSION,
            "minimal_pointer_only": True,
        },
    )
    result.metadata["training_trace_id"] = trace_id
    return trace_id


def run_fixture_case(
    fixture_id: str,
    *,
    conn: sqlite3.Connection,
    output_dir: Path,
    matrix_path: Path = DEFAULT_MATRIX_PATH,
    inventory_path: Path = DEFAULT_INVENTORY_PATH,
    dependency_mode: str = "fixture",
    run_id: str | None = None,
    simulate_missing_artifact_stage: str | None = None,
    force_invalid_transition_stage: str | None = None,
) -> FixtureRunResult:
    registry = build_fixture_registry(matrix_path)
    if fixture_id not in registry:
        raise GoldenFixtureError(f"unknown fixture_id: {fixture_id}")
    spec = registry[fixture_id]
    if not spec.starter_implemented:
        raise GoldenFixtureError(f"{fixture_id} is registered but not implemented by the starter harness")

    ensure_stage_logging_schema(conn)
    ensure_artifact_manifest_schema(conn)
    write_fixture_registry(conn, registry)
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now_iso()
    run_id = run_id or stable_id("golden-fixture-run:", fixture_id, started_at)
    result = FixtureRunResult(
        fixture_result_id=stable_id("golden-fixture-result:", fixture_id, run_id),
        fixture_id=fixture_id,
        run_id=run_id,
        case_id=f"fixture-case:{fixture_id}",
        case_key=f"golden-fixture:{fixture_id}",
        dispatch_id=stable_id("fixture-dispatch:", fixture_id, run_id),
        status="passed",
        started_at=started_at,
        metadata={
            "harness_version": GOLDEN_FIXTURE_HARNESS_VERSION,
            "dependency_mode": dependency_mode,
            "blocker_ids": list(spec.blocker_ids),
            "target_feature_ids": list(spec.target_feature_ids),
        },
    )
    inventory_statuses = load_inventory_statuses(inventory_path)
    for stage in spec.expected_stages:
        should_continue = run_fixture_stage(
            conn,
            spec=spec,
            result=result,
            stage=stage,
            output_dir=output_dir,
            dependency_mode=dependency_mode,
            inventory_statuses=inventory_statuses,
            simulate_missing_artifact_stage=simulate_missing_artifact_stage,
            force_invalid_transition_stage=force_invalid_transition_stage,
        )
        if not should_continue:
            break
    result.completed_at = utc_now_iso()
    write_fixture_training_trace_pointer(conn, result)
    write_result_report_artifact(conn, result, output_dir)
    write_fixture_result(conn, result)
    return result
