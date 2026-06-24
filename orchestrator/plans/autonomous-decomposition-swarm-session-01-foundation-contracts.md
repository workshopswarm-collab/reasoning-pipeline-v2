# Session 01 Plan: Foundation, Contracts, and Control Plane

Master anchors:

- Master plan: `plans/autonomous-decomposition-swarm-implementation-plan.md`
- Shared inventory: `plans/autonomous-decomposition-swarm-feature-inventory.md`
- Machine-readable inventory: `plans/autonomous-decomposition-swarm-feature-inventory.yaml`
- Dependency gate: `python3 plans/check_dependency_gates.py`; append `--report-only` for readiness/blocker summaries and omit it when enforcing a real start gate.
- Live-cutover blocker matrix: `plans/autonomous-decomposition-swarm-live-cutover-blocker-matrix.md`
- Schema-name map: `plans/autonomous-decomposition-swarm-schema-name-map.md`
- Golden fixture matrix: `plans/autonomous-decomposition-swarm-golden-fixture-matrix.md`
- Script placement map: `plans/autonomous-decomposition-swarm-script-placement-map.md`
- Source architecture spec: `/Users/agent2/.openclaw/media/inbound/autonomous-decomposition-swarm-architecture-spec---dbda0f1c----c13d6bea-f02f-4991-8d2c-d69ad5a7dc5a.md`

Primary spec references:

- Section 1.1: normative cutover contract and probability authority boundaries.
- Section 10: authoritative persistence inventory.
- Section 14: failure semantics.
- Section 17.1: existing infrastructure migration map.
- Section 17.2: observability, debuggability, and learning-from-errors.
- Section 18: v2 live cutover, calibration debt, and maturity gates.

## Mission

Create the shared scaffolding every other session depends on: feature tracking, dependency gates, v2 stage vocabulary, stage execution events, artifact manifests, validation/error conventions, persistence schema strategy, golden fixtures, and minimal trace pointer contracts.

This session does not build AMRG, decomposition, retrieval, researcher classification, SCAE math, synthesis, or decision behavior. It makes those sessions possible without drift.

## Runtime Script Placement

Session 1 owns shared Orchestrator scaffolding only. Place any new Session 1 implementation script under `/Users/agent2/.openclaw/orchestrator/scripts` and add its exact path to `plans/autonomous-decomposition-swarm-script-placement-map.md` before implementation.

Planned Session 1 paths:

```text
/Users/agent2/.openclaw/orchestrator/scripts/predquant/ads_handoff.py
/Users/agent2/.openclaw/orchestrator/scripts/bin/wake_decomposer.py
/Users/agent2/.openclaw/orchestrator/scripts/bin/wake_researcher_swarm.py
/Users/agent2/.openclaw/orchestrator/scripts/bin/kick_scae.py
/Users/agent2/.openclaw/orchestrator/scripts/bin/check_ads_script_placement.py
/Users/agent2/.openclaw/orchestrator/scripts/bin/run_ads_pipeline_loop.py
/Users/agent2/.openclaw/orchestrator/scripts/bin/set_ads_pipeline_enabled.py
/Users/agent2/.openclaw/orchestrator/scripts/bin/get_ads_pipeline_control.py
/Users/agent2/.openclaw/orchestrator/scripts/bin/stop_ads_pipeline_loop.py
/Users/agent2/.openclaw/orchestrator/scripts/predquant/ads_pipeline_control.py
/Users/agent2/.openclaw/orchestrator/scripts/predquant/ads_pipeline_runner.py
/Users/agent2/.openclaw/orchestrator/scripts/predquant/ads_case_selector.py
/Users/agent2/.openclaw/orchestrator/scripts/predquant/ads_stage_logging.py
```

Ownership boundaries:

- The wakeup scripts package artifact refs, dependency-gate results, and stage-status transitions only.
- They must not perform QDT generation, leaf research, researcher subagent spawning, or SCAE math.
- If a new foundation script path is needed, update the script placement map and the shared inventory in the same phase.

## Owned Inventory Rows

Directly owned rows:

- `FND-001`: canonical feature inventory and dependency DAG.
- `FND-002`: v2 stage vocabulary, status contract, and execution-event stream.
- `FND-003`: artifact manifest schema and validator.
- `FND-004`: Section 10 migration/schema plan.
- `FND-005`: golden fixture registry and runner.
- `FND-006`: fail-closed validation, safe stage execution logging, and error events.
- `FND-007`: minimal trace pointer contract.
- `AUTO-001`: continuous Orchestrator pipeline runner contract.
- `AUTO-002`: unique eligible-case selector and lease/idempotency guard.
- `AUTO-003`: end-to-end dispatch state machine.
- `AUTO-004`: retry/backoff, stop/drain, and stuck-lease recovery policy.
- `AUTO-005`: continuous loop fixture.
- `AUTO-006`: durable manual `pipeline_enabled` control switch.

Cross-session dependency awareness:

- Session 2 cannot integrate `CTX-*`, `POL-*`, or `AMRG-*` until the relevant artifact/status/persistence contracts from this session exist.
- Session 3 cannot integrate `QDT-*` or `RET-*` until artifact manifests and fixture conventions exist.
- Session 4 cannot integrate `CLS-*` or `VER-*` until schema and persistence conventions exist.
- Session 5 cannot integrate `SCAE-*`, `SYN-001`, `DEC-001`, `PERSIST-001`, `TRACE-*`, `REPLAY-*`, or `CAL-*` until this session provides artifact, persistence, and trace contracts.

## Coordination Rules

1. Before starting a phase, read the master plan and shared inventory.
2. Update only directly owned inventory rows without coordinator review.
3. If another session's dependency or scope must change, add a proposed row or note under a `Proposed Inventory Changes` section in the inventory, or leave a clearly labeled handoff note for Session 1.
4. Each phase must update inventory status when it moves from `not_started` to `in_progress`, `blocked`, `ready_for_integration`, or `done`.
5. Mark a row `done` only when its acceptance checks and tests are recorded in the inventory.
6. Do not mark downstream rows unblocked unless their dependency feature IDs are `done` or have an explicit waiver recorded with owner, reason, and expiry.

Recommended tracking fields to add when converting the inventory to a richer format:

```text
feature_id
owner_session
status
blocked_by
handoff_artifact
acceptance_evidence
last_updated_by
last_updated_at
integration_ready
waiver_ref
```

## Technical Specification

### Continuous Automation Runner

The runner is an Orchestrator-owned control-plane service. It continuously selects one unique eligible case from the existing intake database, drives the full ADS stage sequence, persists SCAE output, releases the case lease, and repeats until stopped.

The durable manual switch is separate from individual runner process state. `pipeline_enabled=false` means no runner may acquire a new case lease, including after process restart. Turning the pipeline off may also write a stop signal, but the enablement check is the hard gate before any new work starts.

Minimum control state record:

```json
{
  "control_state_id": "ads-pipeline-control-current",
  "pipeline_enabled": false,
  "desired_runner_mode": "fixture|non_executing_canary|calibration_debt_production",
  "updated_at": "...",
  "updated_by": "manual|system|fixture",
  "reason": "...",
  "default_disable_action": "no_new_leases|stop_after_current_case|safe_drain_now",
  "acknowledged_by_run_id": null,
  "schema_version": "ads-pipeline-control/v1"
}
```

Minimum runner record:

```json
{
  "pipeline_run_id": "ads-pipeline-run-...",
  "runner_mode": "fixture|non_executing_canary|calibration_debt_production",
  "status": "starting|running|draining|stopped|failed",
  "started_at": "...",
  "stopped_at": null,
  "stop_policy": "none|stop_before_next_case|stop_after_current_case|safe_drain_now",
  "max_cases": null,
  "idle_policy": {
    "on_no_eligible_case": "sleep|exit",
    "idle_sleep_seconds": 60,
    "max_idle_cycles": null
  },
  "dependency_gate_mode": "runtime_integration",
  "active_case_lease_id": null,
  "last_iteration_id": null
}
```

Minimum case lease record:

```json
{
  "case_lease_id": "ads-case-lease-...",
  "pipeline_run_id": "ads-pipeline-run-...",
  "market_id": 0,
  "case_key": "polymarket:...",
  "lease_status": "leased|released|expired|quarantined",
  "lease_owner": "orchestrator",
  "lease_acquired_at": "...",
  "lease_expires_at": "...",
  "dispatch_id": "dispatch-...",
  "idempotency_key": "sha256:...",
  "selected_snapshot_id": 0,
  "selection_policy_ref": "ads-case-selection/v1",
  "release_reason": null
}
```

Minimum loop iteration record:

```json
{
  "loop_iteration_id": "ads-loop-iteration-...",
  "pipeline_run_id": "ads-pipeline-run-...",
  "case_lease_id": "ads-case-lease-...",
  "iteration_number": 1,
  "selected_case_key": "polymarket:...",
  "stage_order": [
    "case_selection",
    "evidence_packet",
    "policy_context",
    "related_market_context",
    "decomposition",
    "retrieval",
    "researcher_classification",
    "classification_verification",
    "scae",
    "synthesis",
    "decision",
    "training_trace",
    "replay_record"
  ],
  "terminal_status": "complete|failed|quarantined|stopped_after_current|no_eligible_case",
  "forecast_artifact_id": "forecast-...",
  "market_prediction_id": 0,
  "error_event_refs": [],
  "retry_summary": {}
}
```

Automation invariants:

- `pipeline_enabled=false` is checked before runner start/restart and before every new case lease.
- A disabled pipeline may finish an already leased case only when the disable action is `stop_after_current_case`; otherwise it must safe-drain to a recoverable state.
- A case cannot enter `pipeline_started` or later stage state unless a lease exists and the selected intake snapshot is valid at forecast time.
- A runner must not acquire two leases for the same active market/case concurrently.
- Repeated restarts must resume from stage status and idempotency keys rather than duplicate forecasts.
- Stop-before-next-case exits only after the current iteration is complete or safely released.
- Safe drain writes enough state for the active case to resume or quarantine without appearing actively running forever.
- Gateway/session handoff failure is retryable separately from model/schema failure.
- Empty eligible-case queues are not failures.

### V2 Stage Vocabulary

Minimum live-cutover stage names:

```text
case_selection
evidence_packet
policy_context
related_market_context
related_market_refresh
decomposition
retrieval
researcher_classification
classification_verification
scae
synthesis
decision
training_trace
replay_record
terminal
```

Each stage status record should include:

```json
{
  "case_id": "case-...",
  "case_key": "...",
  "dispatch_id": "dispatch-...",
  "stage": "decomposition",
  "status": "not_started|running|blocked|failed|complete|waived",
  "stage_attempt_id": "stage-attempt-...",
  "started_at": "...",
  "completed_at": "...",
  "duration_ms": 0,
  "input_artifacts": ["artifact-manifest-id"],
  "output_artifacts": ["artifact-manifest-id"],
  "dependency_feature_ids": ["QDT-002"],
  "blocking_feature_ids": [],
  "reason_codes": [],
  "latest_execution_event_ids": [],
  "error_event_ids": [],
  "replay_command": "python3 ... --case-id ... --dispatch-id ... --stage decomposition",
  "metadata": {}
}
```

### Stage Execution Event Contract

`MIG-002` must include one uniform execution-event stream for live operations debugging. Stage status answers "where is the case now"; stage execution events answer "what exactly happened while the stage ran." Every Orchestrator stage wrapper must write these events even when the wrapped component also writes domain-specific diagnostics.

Required event types:

```text
stage_started
stage_completed
stage_failed
stage_blocked
retry_scheduled
artifact_validation_failed
```

Minimum `v2-stage-execution-event/v1` record:

```json
{
  "execution_event_id": "stage-exec-event-...",
  "schema_version": "v2-stage-execution-event/v1",
  "pipeline_run_id": "ads-pipeline-run-...",
  "case_lease_id": "ads-case-lease-...",
  "case_id": "case-...",
  "case_key": "...",
  "dispatch_id": "dispatch-...",
  "stage": "retrieval",
  "stage_attempt_id": "stage-attempt-...",
  "event_type": "stage_started|stage_completed|stage_failed|stage_blocked|retry_scheduled|artifact_validation_failed",
  "event_status": "info|warning|error",
  "event_at": "...",
  "started_at": "...",
  "completed_at": "...",
  "duration_ms": 0,
  "attempt_number": 1,
  "max_attempts": 3,
  "runner_ref": "ads-runner:...",
  "agent_or_component_ref": "orchestrator|decomposer|researcher-swarm|scae",
  "script_path": "/Users/agent2/.openclaw/orchestrator/scripts/bin/run_ads_pipeline_loop.py",
  "command_sha256": "sha256:...",
  "input_artifact_refs": [],
  "output_artifact_refs": [],
  "validation_result_refs": [],
  "error_event_id": null,
  "failure_class": null,
  "safe_exception_class": null,
  "safe_exception_message": null,
  "traceback_sha256": null,
  "stdout_artifact_ref": null,
  "stderr_artifact_ref": null,
  "bounded_log_artifact_ref": null,
  "redaction_status": "not_needed|redacted|blocked_unsafe",
  "resource_counters": {
    "wall_ms": 0,
    "cpu_ms": null,
    "max_rss_mb": null
  },
  "retry_policy_ref": null,
  "next_retry_at": null,
  "replay_command": "python3 ... --case-id ... --dispatch-id ... --stage retrieval --attempt 1",
  "safe_metadata": {}
}
```

Stage wrapper rules:

- Write `stage_started` before calling a component or handoff script.
- Write `stage_completed` only after output artifacts are manifested, validated, and linked to the status snapshot.
- Write `stage_failed` for terminal component, schema, model, handoff, or contract failures; link the related `v2_pipeline_error_events` row.
- Write `stage_blocked` when dependencies, sufficiency gates, source access requirements, or policy gates prevent safe progress without treating the case as a crashed process.
- Write `retry_scheduled` for retryable gateway/session/source/transient failures, including attempt count, next retry time, and retry policy ref.
- Write `artifact_validation_failed` whenever a produced artifact fails schema, hash, temporal-isolation, or forbidden-field validation.
- Store stdout, stderr, traceback text, browser logs, and large component logs only behind bounded artifact refs after secret redaction. The execution event stores hashes, refs, safe exception summaries, and grouping fields, not raw secret-bearing logs.
- Every execution event must carry enough correlation fields to join case lease, dispatch, stage status, artifacts, error event, retry policy, and replay command.

### Artifact Manifest Contract

Every v2 artifact must have an auditable manifest entry:

```json
{
  "artifact_id": "artifact:...",
  "artifact_type": "question_decomposition",
  "schema_version": "question-decomposition/v1",
  "case_id": "case-...",
  "case_key": "...",
  "dispatch_id": "dispatch-...",
  "stage": "decomposition",
  "path": "qualitative-db/40-research/cases/.../question-decomposition.json",
  "sha256": "sha256:...",
  "generated_at": "...",
  "forecast_timestamp": "...",
  "source_cutoff_timestamp": "...",
  "input_manifest_ids": [],
  "validation_status": "valid|invalid|warning|not_validated",
  "validator_version": "v2-artifact-validator/1",
  "temporal_isolation_status": "pass|fail|not_applicable",
  "metadata": {}
}
```

### Persistence Strategy

The spec names many first-class records. Implement them in layers:

1. Foundation tables for manifests, status, stage execution events, error events, replay manifests, replay results, failure groups, fixture registry, fixture results, and trace pointers.
2. Component-specific JSON artifact schemas and generic manifest linking.
3. Named table migrations for cutover-critical slices before runtime integration.
4. Maturity-only persistence after the live-cutover path is fixture-valid.

Do not hide cutover-critical records in a single untyped `details` blob once runtime integration begins. The current migration may use generic foundation tables as a temporary bootstrap, but each persisted slice from Section 10 needs either a named table, schema file, or explicit external artifact contract before implementation starts.

Session 1 owns the shared migration matrix, not all component writes. Other sessions own their component write paths, but Session 1 must ensure the matrix answers four questions for every migration group:

```text
what record is stored
which feature/session produces it
which table/schema/artifact receives it
which future tuning question it supports
```

### Fail-Closed Validation

Validation result vocabulary:

```text
valid
valid_with_warnings
invalid_retryable
invalid_terminal
waived_by_policy
not_applicable
```

Error events should distinguish:

```text
schema_validation_failed
dependency_not_ready
temporal_isolation_failed
forbidden_probability_field
missing_required_artifact
invalid_stage_transition
unowned_inventory_update
amrg_anchor_required_unrepairable
scae_probability_authority_violation
decision_probability_override_attempt
```

Minimum `v2-pipeline-error-event/v1` records must link back to the failed execution event:

```json
{
  "error_event_id": "pipeline-error-...",
  "schema_version": "v2-pipeline-error-event/v1",
  "execution_event_id": "stage-exec-event-...",
  "case_id": "case-...",
  "dispatch_id": "dispatch-...",
  "stage": "retrieval",
  "failure_class": "schema_validation_failed",
  "failure_grouping_key": "retrieval:schema_validation_failed:missing_required_artifact",
  "retryability": "retryable|terminal|blocked|waived",
  "safe_message": "bounded operator-safe summary",
  "safe_metadata": {},
  "replay_command": "python3 ...",
  "unsafe_secret_exclusion_status": "passed|blocked",
  "bounded_log_artifact_refs": []
}
```

## Phase 0: Anchor and Inventory Audit

Goal: confirm the session is aligned with the master plan and all owned rows are present.

Pseudocode:

```python
master = read_markdown("plans/autonomous-decomposition-swarm-implementation-plan.md")
inventory = read_markdown("plans/autonomous-decomposition-swarm-feature-inventory.md")
owned = ["FND-001", "FND-002", "FND-003", "FND-004", "FND-005", "FND-006", "FND-007"]

for feature_id in owned:
    assert feature_id in inventory
    assert owner(feature_id) == "Session 1"

assert "Section 10" in master
assert "Wave A" in master
```

Tests:

- Static check that every owned feature ID appears exactly once.
- Static check that every phase below maps to at least one owned feature ID.
- Manual review that no Session 1 phase implements another session's runtime behavior.

Checklist:

- [x] Inventory rows exist for all `FND-*` features.
- [x] Dependencies are visible.
- [x] Master plan references are current.
- [x] Inventory status updated for `FND-001`.

## Phase 1: Dependency DAG and Inventory Tracking

Goal: make the shared inventory the active coordination surface.

Implementation shape:

- Keep the markdown inventory human-readable.
- Maintain `plans/autonomous-decomposition-swarm-feature-inventory.yaml` as the executable, JSON-compatible dependency inventory.
- Keep the Markdown inventory and machine-readable inventory synchronized in the same change when ownership, dependency, or stage labels move.
- Add ownership rules and waiver conventions.
- Maintain `python3 plans/check_dependency_gates.py` as the dependency-check command for fixture, runtime integration, calibration-debt clearance, and autonomous optimization maturity modes.
- The checker must reject unknown dependencies, dependency cycles, malformed waivers, and runtime integration before upstream rows are `ready_for_integration`, `done`, or explicitly waived.
- Maintain the supporting coordination artifacts:
  - `plans/autonomous-decomposition-swarm-live-cutover-blocker-matrix.md`
  - `plans/autonomous-decomposition-swarm-schema-name-map.md`
  - `plans/autonomous-decomposition-swarm-golden-fixture-matrix.md`

Pseudocode:

```python
def can_start(feature_id, desired_mode):
    row = inventory.lookup(feature_id)
    if desired_mode == "fixture":
        return True
    for dep in row.dependencies:
        dep_row = inventory.lookup(dep)
        if dep_row.status not in ["done", "ready_for_integration"]:
            if not valid_waiver(dep, feature_id):
                return False
    return True

def update_status(feature_id, new_status, evidence):
    row = inventory.lookup(feature_id)
    assert current_session == row.owner_session
    assert evidence or new_status in ["not_started", "in_progress", "blocked"]
    row.status = new_status
    row.acceptance_evidence = evidence
    row.last_updated_by = current_session
    row.last_updated_at = now()
```

Testing suite:

- Unit: dependency checker rejects missing feature IDs.
- Unit: dependency checker rejects integration when upstream rows are not ready.
- Unit: dependency checker rejects feature dependency cycles.
- Unit: owned row update passes and unowned row update fails.
- Unit: waiver requires owner, reason, expiry, and target feature.
- Integration: a downstream fixture-mode task can proceed while integration-mode is blocked.

Completion checklist:

- [ ] Inventory ownership rules are written.
- [ ] Markdown and machine-readable inventories agree on owner, stage, status, and dependencies.
- [ ] Dependency gate semantics are written.
- [ ] Dependency gate command validates clean inventory and blocks unready runtime rows.
- [ ] Waiver semantics are written.
- [ ] Blocker matrix, schema-name map, and fixture matrix are linked from this plan.
- [ ] `FND-001` marked `done` only after acceptance evidence is recorded.

## Phase 2: V2 Stage Status Model

Goal: make v2 work visible to sequencers, health checks, and future workers.

Implementation shape:

- Define stage enum.
- Define legal transitions.
- Define status snapshot schema.
- Define stage execution event schema and lifecycle event vocabulary.
- Define stuck-stage and retry metadata.
- Preserve legacy labels only as compatibility wrappers, never as hiding places for v2 stages.

Pseudocode:

```python
STAGES = [
    "case_selection",
    "evidence_packet",
    "policy_context",
    "related_market_context",
    "related_market_refresh",
    "decomposition",
    "retrieval",
    "researcher_classification",
    "classification_verification",
    "scae",
    "synthesis",
    "decision",
    "training_trace",
    "replay_record",
    "terminal",
]

ALLOWED_TRANSITIONS = {
    "not_started": ["running", "waived"],
    "running": ["complete", "failed", "blocked"],
    "blocked": ["running", "failed", "waived"],
    "failed": ["running", "terminal"],
    "complete": [],
    "waived": [],
}

def record_stage_status(case_id, dispatch_id, stage, status, artifacts, reason_codes):
    assert stage in STAGES
    assert status in ALLOWED_TRANSITIONS
    persist("v2_stage_status_snapshots", payload)

def record_stage_execution_event(context, event_type, **fields):
    assert context.stage in STAGES
    assert event_type in {
        "stage_started",
        "stage_completed",
        "stage_failed",
        "stage_blocked",
        "retry_scheduled",
        "artifact_validation_failed",
    }
    assert fields["redaction_status"] in {"not_needed", "redacted", "blocked_unsafe"}
    assert fields.get("replay_command")
    persist("v2_stage_execution_events", payload)
```

Testing suite:

- Unit: unknown stage is rejected.
- Unit: illegal transition is rejected.
- Unit: each stage can record input and output artifact IDs.
- Unit: every allowed execution event type records stage attempt ID, replay command, and safe log refs or explicit no-log reason.
- Unit: unsafe raw stderr/stdout/traceback content is rejected unless redacted into bounded artifact refs.
- Integration: fixture run produces visible status for all Wave B stages.
- Integration: fixture run emits `stage_started` and terminal execution events for every stage wrapper.
- Regression: legacy `dispatch/swarm/synthesis/decision` labels do not hide v2 stage failures.

Completion checklist:

- [ ] Stage enum written.
- [ ] Status schema written.
- [ ] Stage execution event schema written.
- [ ] Stage wrapper lifecycle event helpers written.
- [ ] Transition rules written.
- [ ] Failure/stuck metadata written.
- [ ] Fixture status example written.
- [ ] `FND-002` updated in inventory.

## Phase 3: Artifact Manifest and Validation Core

Goal: every session can register and validate artifacts consistently.

Implementation shape:

- Schema for artifact manifests.
- SHA-256 digest helper contract.
- Source cutoff and forecast timestamp handling.
- Validation result contract.
- Manifest linking between artifacts.

Pseudocode:

```python
def materialize_artifact_manifest(artifact_type, schema_version, path, context):
    content = read_bytes(path)
    manifest = {
        "artifact_id": make_artifact_id(context, artifact_type),
        "artifact_type": artifact_type,
        "schema_version": schema_version,
        "case_id": context.case_id,
        "dispatch_id": context.dispatch_id,
        "path": str(path),
        "sha256": sha256(content),
        "generated_at": context.generated_at,
        "forecast_timestamp": context.forecast_timestamp,
        "source_cutoff_timestamp": context.source_cutoff_timestamp,
        "input_manifest_ids": context.input_manifest_ids,
        "validation_status": "not_validated",
    }
    validate_manifest_schema(manifest)
    persist_manifest(manifest)
    return manifest

def validate_artifact(manifest, schema):
    payload = read_json(manifest.path)
    schema_validate(schema, payload)
    assert sha256(read_bytes(manifest.path)) == manifest.sha256
    return validation_result("valid")
```

Testing suite:

- Unit: manifest rejects missing path, digest, schema version, and case identity.
- Unit: changed artifact content after manifest creation fails digest validation.
- Unit: invalid schema produces `invalid_terminal` or `invalid_retryable`.
- Integration: fixture artifacts link through input/output manifest IDs.
- Temporal: manifest records source cutoff and forecast timestamp separately.

Completion checklist:

- [ ] Artifact manifest schema written.
- [ ] Digest contract written.
- [ ] Validation result vocabulary linked.
- [ ] Manifest persistence surface identified.
- [ ] `FND-003` updated in inventory.

## Phase 4: Section 10 Persistence Migration Plan

Goal: convert Section 10's persistence inventory into an implementation order.

Implementation shape:

- Keep foundation migration idempotent.
- Add named table plan for cutover-critical slices.
- Identify maturity-only tables to postpone.
- Require schema or artifact contract before any implementation writes records.
- Add the shared `MIG-001` to `MIG-013` migration matrix from the feature inventory.
- Treat `MIG-001` and `MIG-002` as Session 1 implementation-owned; treat the rest as component-owned write paths that Session 1 validates for table/schema coverage.

Migration groups:

| Migration ID | Owner | Required Contract | Simple Purpose |
| --- | --- | --- | --- |
| `MIG-001` | Session 1 | `write_artifact_manifest()` and `artifact_manifest`/manifest schema | Records artifact schema, hash, timestamp, producer, and lineage for exact replay. |
| `MIG-002` | Session 1 | `write_stage_status()`, `write_stage_execution_event()`, `write_pipeline_error_event()` and stage/status/execution/error tables | Records where a case is in the pipeline, what happened during every stage attempt, safe log refs, replay commands, and why it failed, blocked, retried, or downgraded. |
| `MIG-013` | Session 1 | `write_pipeline_run()`, `write_pipeline_control_state()`, `acquire_case_lease()`, `write_pipeline_loop_iteration()`, `write_pipeline_stop_signal()`, `release_case_lease()` and control/runner/lease/iteration/stop tables | Records durable enable/disable state, continuous automation runs, case leases, loop iterations, stop/drain requests, retries, idle cycles, terminal status, and duplicate-prevention evidence. |
| `MIG-012` | Session 2 | `write_case_intake_handoff()`, `write_ads_case_contract()` and case contract table/artifact schema | Binds existing intake `markets` / `market_snapshots` rows, dispatch identity, source cutoff, raw payload hashes, prediction-time market baseline, and artifact refs before evidence packet creation. |
| `MIG-003` | Session 3 | `write_decomposition_run()` and QDT run/leaf tables or artifact schema | Records selected decomposition, leaves, branches, dependency groups, and model provenance. |
| `MIG-004` | Session 3 | `write_retrieval_packet()` and retrieval/source/claim/missingness tables or artifact schema | Records evidence provenance and retrieval quality for retrieval tuning. |
| `MIG-005` | Session 2 | `write_related_market_context()` and AMRG candidate/edge/timing/refresh tables or artifact schema | Records related-market signals and their validation strength. |
| `MIG-006` | Session 4 | `write_leaf_research_assignments()`, `write_researcher_context_isolation_audits()`, `write_researcher_classifications()`, `write_verification_slices()`, `write_researcher_coverage_proofs()`, `write_researcher_escalation_decisions()`, and `write_research_sufficiency_reconciliation()` | Records compact leaf assignment packets, context-isolation audits, researcher NLI output, extracted values, quality dimensions, evidence-review coverage, adaptive escalation decisions, side checks, and verifier results. |
| `MIG-007` | Session 5 | `write_scae_ledger()` and SCAE ledger/update/branch/diagnostic tables | Records the full numeric audit trail and final SCAE probability fields. |
| `MIG-008` | Session 5 | `write_forecast_decision()` and forecast/decision table | Records SCAE production probability plus actionability status without creating a second probability authority. |
| `MIG-009` | Session 5 primary; Session 6 contributor for `TRACE-002` | `write_minimal_training_trace()`, `write_replay_manifest()`, `write_full_training_trace_materialization()` and trace/replay tables | Records replayable hashes and pointers for first-100+ runs and later full trace materialization. |
| `MIG-010` | Session 5 | `write_resolution_score()` and outcome/scoring table or `market_predictions` extension | Records outcome, Brier, log-loss, market baseline, reliability bucket, and resolution provenance. |
| `MIG-011` | Session 6 | `write_calibration_candidate()`, `promote_policy_pointer()`, `write_policy_rollback_event()` and tuning lane tables | Records policy candidates, active pointers, canaries, rollback pointers, diagnostics, and promotions. |

Cutover-critical surfaces:

```text
artifact_manifest
v2_stage_status_snapshots
v2_pipeline_error_events
ads_pipeline_runs
ads_pipeline_control_state
ads_case_leases
ads_pipeline_loop_iterations
ads_pipeline_stop_signals
markets
market_snapshots
case_intake_handoff_records
ads_case_contracts
qdt_decomposition_runs
qdt_required_research_questions
qdt_decomposition_miss_labels
persona_evidence_classification_slices
persona_evidence_provenance_slices
evidence_direction_verification_slices
evidence_quality_verification_slices
normalized_supplemental_evidence
source_access_failure_slices
missingness_signal_slices
retrieval_quality_slices
related_market_relationship_slices
amrg_causal_graph_safety_slices
related_market_prior_anchor_slices
related_market_refresh_events
qdt_amrg_anchor_dependency_slices
scae_mechanism_family_assignment_slices
market_family_contract_records
family_displacement_signal_slices
scae_family_consistency_diagnostic_slices
scae_log_odds_update_slices
scae_conditional_branch_slices
scae_conditional_prior_audit_slices
scae_calibration_diagnostic_slices
scae_cross_leaf_dependency_slices
scae_branch_subledger_slices
scae_ledger_outputs
forecast_decision_records
market_predictions
outcome_scoring_records
calibration_candidate_records
calibration_lane_pointer_records
market_regime_tag_slices
v2_replay_manifests
v2_replay_result_records
golden_fixture_case_registry
golden_fixture_case_results
training_trace_runs
```

Pseudocode:

```python
def assert_persistence_surface(feature_id):
    row = inventory.lookup(feature_id)
    for surface in row.persistence_surfaces:
        if not table_exists(surface) and not schema_file_exists(surface) and not external_artifact_contract_exists(surface):
            raise PersistenceContractMissing(surface)

def assert_migration_group_contract(migration_id):
    row = migration_inventory.lookup(migration_id)
    assert row.owner_session
    assert row.write_path_contract
    assert row.tuning_purpose
    assert row.destination_table or row.schema_file or row.external_artifact_contract
    assert row.runtime_integration_blocked_until_contract_ready

def validate_write_path_contract(write_path):
    assert write_path.idempotency_key
    assert "case_id" in write_path.required_fields or "case_key" in write_path.required_fields
    assert "dispatch_id" in write_path.required_fields or write_path.scope in ["global_policy", "resolved_outcome"]
    assert "schema_version" in write_path.required_fields
    assert "produced_at" in write_path.required_fields
    assert write_path.forbidden_authority_violations == []

def apply_migration(conn, migration):
    conn.executescript(migration.sql)
    record_migration(migration.id, sha256(migration.sql))
```

Testing suite:

- Migration: idempotent apply on empty database.
- Migration: idempotent reapply on existing database.
- Schema: each cutover-critical table has primary identity, case/dispatch refs where applicable, generated timestamp, and metadata.
- Schema: each `MIG-001` to `MIG-013` row has an owner, write path, table/schema/artifact destination, and tuning purpose.
- Contract: runtime integration fails if a component writes a tuning-critical surface without a migration group contract.
- Contract: write paths are idempotent on stable dispatch/run/artifact keys.
- Inventory: every persisted feature row names a persistence surface.
- Regression: no implementation task writes an unlisted Section 10 slice.

Completion checklist:

- [ ] Cutover-critical table list written.
- [ ] Maturity-only table list written.
- [ ] `MIG-001` to `MIG-013` matrix written and cross-linked to feature rows.
- [ ] `MIG-001` artifact manifest contract specified.
- [ ] `MIG-002` stage/status/execution/error contract specified.
- [ ] Component-owned write paths have destination table/schema placeholders.
- [ ] Migration order written.
- [ ] Persistence contract check written or specified.
- [ ] `FND-004` updated in inventory.

## Phase 5: Golden Fixture Registry and Fail-Closed Harness

Goal: make fixture-first integration possible across all sessions.

Implementation shape:

- Use `plans/autonomous-decomposition-swarm-golden-fixture-matrix.md` as the authoritative fixture list.
- Implement the Wave B starter fixtures first: minimal binary market, family-aware binary child, AMRG no-related-context, weak-context AMRG, conditional-anchor negative, invalid probability-authoring, and decision override attempt.
- Keep the expanded cutover and maturity fixtures in the matrix so downstream workers can add them without changing the harness contract.
- Every fixture result must write a stage/status record, artifact manifests, and structured validation/error outputs.

Pseudocode:

```python
def run_fixture_case(fixture_id):
    fixture = load_fixture(fixture_id)
    result = FixtureResult(fixture_id=fixture_id)
    for stage in fixture.expected_stages:
        if not dependencies_ready(stage.feature_ids, mode="fixture"):
            result.record(stage, "blocked")
            break
        outcome = validate_stage_fixture(stage, fixture)
        result.record(stage, outcome.status, outcome.artifacts)
        if outcome.status.startswith("invalid"):
            break
    persist_fixture_result(result)
    return result
```

Testing suite:

- Fixture: minimal case reaches expected stub terminal state.
- Fixture: missing artifact fails closed.
- Fixture: invalid stage transition fails closed.
- Fixture: probability override attempt fails closed.
- Fixture: downstream integration gate blocks when upstream dependency is not ready.
- Fixture matrix: every `FIX-*` row has owner session, target feature IDs, expected outcome, and status.

Completion checklist:

- [ ] Fixture registry schema written.
- [ ] Fixture result schema written.
- [ ] Minimal fixture spec written.
- [ ] Negative fixture specs written.
- [ ] Golden fixture matrix linked and treated as authoritative.
- [ ] Error event contract written.
- [ ] `FND-005` and `FND-006` updated in inventory.

## Phase 6: Minimal Training Trace Pointer Contract

Goal: ensure first-100 direct-cutover runs can be replayed later without giving traces live authority.

Implementation shape:

- Synchronous minimal trace pointer only.
- Full trace materialization is Session 6 maturity work after Session 5 writes minimal traces and replay manifests.
- Trace cannot alter retrieval, SCAE, synthesis, decision, or production forecast persistence.

Pseudocode:

```python
def write_training_trace_minimal(context, artifact_manifests):
    trace = {
        "trace_id": make_trace_id(context),
        "case_id": context.case_id,
        "dispatch_id": context.dispatch_id,
        "forecast_timestamp": context.forecast_timestamp,
        "artifact_manifest_ids": [m.artifact_id for m in artifact_manifests],
        "artifact_hashes": {m.artifact_id: m.sha256 for m in artifact_manifests},
        "trace_status": "minimal_pointer_written",
        "live_authority": "none",
    }
    assert trace["live_authority"] == "none"
    persist("training_trace_runs", trace)
    return trace
```

Testing suite:

- Unit: trace requires artifact pointers and hashes.
- Unit: trace cannot include replacement probability.
- Integration: fixture run writes exactly one minimal trace pointer.
- Regression: missing trace pointer fails cutover readiness but does not mutate forecast.

Completion checklist:

- [ ] Minimal trace schema written.
- [ ] Trace non-authority rule written.
- [ ] First-100 replay relationship documented.
- [ ] `FND-007` updated in inventory.

## Phase 7: Continuous Automation Runner and Case Leases

Goal: make the ADS pipeline capable of repeatedly selecting eligible cases and running the full handoff spine until stopped.

Implementation shape:

- Define `pipeline_run`, `case_lease`, `loop_iteration`, and `stop_signal` schemas.
- Define durable `pipeline_control_state` schema with `pipeline_enabled`.
- Implement unique eligible-case selection over existing intake rows.
- Implement lease acquisition with idempotency key and expiry.
- Implement stage sequence orchestration as a state machine over the handoff scripts.
- Route every live stage call through `run_stage_with_execution_events()` so status snapshots, execution events, bounded log refs, error events, retry decisions, and replay commands are written consistently.
- Implement stop-before-next-case, stop-after-current-case, and safe-drain behavior.
- Implement manual enable/disable commands and make lease acquisition refuse when disabled.
- Implement retry/backoff classes for transient handoff errors versus non-retryable schema/validation errors.
- Implement stuck-lease recovery and same-case cleanup rules.

Pseudocode:

```python
def run_ads_pipeline_loop(policy):
    control = read_pipeline_control_state()
    if not control.pipeline_enabled:
        return "pipeline_disabled"
    run = write_pipeline_run(status="running", runner_mode=policy.mode)
    while True:
        control = read_pipeline_control_state()
        if not control.pipeline_enabled:
            write_pipeline_loop_iteration(run, terminal_status="pipeline_disabled_no_new_lease")
            return stop_runner(run, reason="pipeline_disabled")

        stop = read_stop_signal(run.pipeline_run_id)
        if stop.policy == "stop_before_next_case":
            return stop_runner(run, reason="stop_before_next_case")

        lease = acquire_next_case_lease(policy.selection, run.pipeline_run_id)
        if not lease:
            write_pipeline_loop_iteration(run, terminal_status="no_eligible_case")
            if policy.idle.on_no_eligible_case == "exit":
                return stop_runner(run, reason="no_eligible_case")
            sleep(policy.idle.idle_sleep_seconds)
            continue

        try:
            contract = run_stage_with_execution_events("evidence_packet", lease, build_ads_case_contract_from_lease)
            evidence = run_stage_with_execution_events("evidence_packet", lease, build_evidence_packet, contract)
            profile = run_stage_with_execution_events("policy_context", lease, resolve_tuning_profile_context, contract, evidence)
            amrg = run_stage_with_execution_events("related_market_context", lease, build_related_live_market_context, contract, evidence, profile)
            qdt = run_stage_with_execution_events("decomposition", lease, wake_decomposer, contract, evidence, profile, amrg)
            research = run_stage_with_execution_events("researcher_classification", lease, wake_researcher_swarm, contract, evidence, profile, amrg, qdt)
            ledger = run_stage_with_execution_events("scae", lease, kick_scae, contract, qdt, research)
            synthesis = run_stage_with_execution_events("synthesis", lease, run_synthesis_annotation, contract, ledger)
            decision = run_stage_with_execution_events("decision", lease, run_decision_gate, contract, ledger, synthesis)
            prediction = run_stage_with_execution_events("decision", lease, persist_scae_forecast, contract, ledger, decision)
            run_stage_with_execution_events("training_trace", lease, write_minimal_trace_and_replay, contract, qdt, research, ledger, prediction)
            write_pipeline_loop_iteration(run, lease, terminal_status="complete",
                                          market_prediction_id=prediction.id)
            release_case_lease(lease, reason="complete")
        except RetryableStageError as exc:
            record_retry_or_backoff(run, lease, exc)
        except NonRetryableStageError as exc:
            write_pipeline_error_event(exc, case_lease_id=lease.id)
            quarantine_or_soft_fail_case(lease, exc)
            release_case_lease(lease, reason="quarantined")

        if read_stop_signal(run.pipeline_run_id).policy in {"stop_after_current_case", "safe_drain_now"}:
            return stop_runner(run, reason="stop_after_current_case")
```

Testing suite:

- Unit: selector cannot lease the same market/case twice concurrently.
- Unit: disabled pipeline refuses runner start and refuses new lease acquisition.
- Unit: disabling during an active case follows configured default disable action.
- Unit: no valid pre-forecast snapshot means no lease is acquired.
- Unit: stop-before-next-case exits before acquiring a new lease.
- Unit: stop-after-current-case finishes the active dispatch then exits.
- Unit: transient handoff failure writes retry/backoff state and keeps lease recoverable.
- Unit: non-retryable validation failure writes error event and releases/quarantines lease.
- Unit: retryable and non-retryable stage wrapper paths both write execution events with replay commands and safe log refs.
- Integration fixture: two eligible markets produce two unique forecasts in order, then runner stops cleanly.
- Restart fixture: interrupted runner resumes or quarantines from last stage status without duplicate `market_predictions` writes.

Completion checklist:

- [ ] `AUTO-001` to `AUTO-005` inventory rows updated.
- [ ] `AUTO-006` inventory row updated.
- [ ] `MIG-013` schema names resolved.
- [ ] Runner, selector, lease, control-state, and stop-signal script paths are in the placement map.
- [ ] Loop iteration records include case, lease, stage, terminal status, and forecast refs.
- [ ] Stop/drain controls are deterministic and test-covered.
- [ ] Manual enable/disable switch is deterministic and test-covered.
- [ ] Duplicate lease and duplicate forecast persistence are rejected.

## End-to-End Completion Checklist

- [ ] All `FND-*` rows have acceptance evidence in the shared inventory.
- [ ] All `AUTO-*` rows have acceptance evidence in the shared inventory.
- [ ] Every other session has a dependency gate to this session's outputs.
- [ ] Stage/status model is visible to all sessions.
- [ ] Artifact manifest contract is usable by all sessions.
- [ ] Persistence surface plan covers every cutover-critical Section 10 record.
- [ ] Fixture harness can run at least one positive and one negative case.
- [ ] Fail-closed validation produces structured error events.
- [ ] Minimal trace pointer contract exists and is non-authoritative.
- [ ] Master inventory updated with handoff artifacts.
