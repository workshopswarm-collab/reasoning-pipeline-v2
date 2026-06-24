# Session 06 Plan: Evaluator/Tuning Agent and Optimization Maturity

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

- Section 1.1: calibration debt, promoted policy pointers, non-authoritative replay/canary/evaluator records, and post-ledger calibration limits.
- Section 10 and 10.1: training trace, replay, scoring, calibration, and tuning persistence.
- Section 11: SCAE constants, component diagnostics, cap stack, dependence discounts, and calibration.
- Section 16: tunable registry, profile resolution, canary, rollback, and lane ownership.
- Section 18: calibration-debt clearance and autonomous optimization maturity gates.

## Mission

Build the autonomous evaluator/tuning lane after the live path is replayable. This session turns resolved replay, scorecards, full trace materializations, and component diagnostics into non-authoritative policy candidates. It owns maturity infrastructure, not the live forecast path.

Session 6 must never write production forecasts, rewrite base policy files, clear calibration debt from trace completeness alone, or apply unpromoted numeric weights. It writes candidates, diagnostics, canary state, active pointer proposals, rollback pointers, and maturity gates. Live dispatch reads only valid promoted pointers.

## Runtime Script Placement

Session 6 maturity work defaults to Orchestrator unless VM later creates a dedicated evaluator/tuning agent. Place evaluator, replay, tuning, canary, rollback, and maturity scripts under `/Users/agent2/.openclaw/orchestrator/scripts` for now. Add every concrete script path to `plans/autonomous-decomposition-swarm-script-placement-map.md` before implementation.

Ownership boundaries:

- Session 6 may consume SCAE scorecards, replay manifests, trace materializations, and component diagnostics.
- It must not write production forecasts or modify base policy files.
- Candidate policies, active pointer proposals, canary state, and rollback pointers remain non-authoritative until promoted through the configured gates.

## Owned Inventory Rows

Directly owned rows:

- `TRACE-002`: async full trace materialization.
- `CAL-002`: lane queues, active pointers, canaries, lane health, and rollback.
- `CAL-003`: retrieval-policy calibration snapshots.
- `CAL-004`: decomposer-profile and decision/actionability profile calibration lanes.
- `CAL-005`: autonomous optimization maturity gate.

Consumed rows owned by other sessions:

- `TRACE-001`, `MODEL-004`, `REPLAY-001`, `CAL-001`: Session 5 trace, model provenance, replay, scoring, and debt gates.
- `POL-001`, `POL-003`: Session 2 tunable registry and effective tuning profile context.
- `RET-003`, `RET-004`: Session 3 retrieval quality and claim-family provenance.
- `QDT-003`, `QDT-004`: Session 3 decomposition validation and AMRG anchor dependency contracts.
- `DEC-001`, `PERSIST-001`: Session 5 decision/actionability and SCAE-only persistence boundaries.

## Coordination Rules

1. Update only Session 6 rows directly in the shared inventory.
2. Run `python3 plans/check_dependency_gates.py --feature-id <ID> --mode autonomous_optimization_maturity` before starting runtime maturity work for any owned row.
3. Fixture-mode maturity tests may run early, but runtime maturity integration waits for upstream rows to be `ready_for_integration`, `done`, or explicitly waived.
4. If a missing table, schema, or artifact contract is discovered, update the schema-name map and add a proposed inventory note instead of silently writing an untracked surface.
5. Session 6 can contribute `TRACE-002` records to the `MIG-009` trace/replay contract, but it does not own Session 5 minimal trace or replay manifests.
6. Session 6 owns `MIG-011` calibration/tuning records and must keep the machine-readable inventory, Markdown inventory, and coverage map synchronized.
7. Candidate policies are non-authoritative until promotion writes a valid active pointer. Candidate generation must not mutate base policy files.
8. Emergency conservative overlays may only reduce risk or widen uncertainty, and must record owner lane, reason, bounds, expiry, and rollback semantics.

## Migration and Write Path Ownership

Session 6 owns `MIG-011` and contributes full trace materialization to `MIG-009`.

Required write paths:

```text
write_full_training_trace_materialization
write_calibration_candidate
write_calibration_component_diagnostics
write_calibration_lane_health
write_calibration_canary_state
promote_policy_pointer
write_policy_rollback_event
write_retrieval_policy_snapshot
write_decomposer_profile_candidate
write_decision_actionability_candidate
write_emergency_conservative_overlay
write_optimization_maturity_result
```

Write-path rules:

- Every record has stable identity, `case_id`/`dispatch_id` when applicable, produced timestamp, source replay/scoring refs, schema version, policy pointer refs, lane owner, and content hash.
- Every candidate declares subsystem scope: `scae`, `retrieval`, `decomposer`, `decision_actionability`, `profile_resolution`, or `emergency_conservative`.
- Every candidate declares risk tier, bounds, allowed deployment stage, canary rule, rollback pointer, protected component diagnostics, and promotion gate status.
- No write path can persist `production_forecast_prob`, `canonical_probability`, or any replacement live probability.

## Technical Specification

### Tuning Lane Vocabulary

```text
candidate_recorded
diagnostics_ready
holdout_failed
holdout_passed
canary_pending
canary_running
canary_failed
canary_passed
promoted_active_pointer
rolled_back
expired
blocked
```

Lane scopes:

```text
scae_constants
post_ledger_calibration
retrieval_policy
decomposer_profile
decision_actionability_profile
effective_tuning_profile
emergency_conservative_overlay
```

### Candidate Record Skeleton

```json
{
  "artifact_type": "calibration_candidate",
  "schema_version": "calibration-candidate/v1",
  "candidate_id": "cal-candidate:...",
  "lane_id": "post_ledger_calibration",
  "owner_session": "Session 6",
  "source_replay_cohort_ids": [],
  "source_scorecard_refs": [],
  "source_trace_materialization_refs": [],
  "policy_snapshot_ref": "sha256:...",
  "base_policy_ref": "sha256:...",
  "changed_parameters": [],
  "bounds_check_status": "passed|failed",
  "component_diagnostics_ref": "sha256:...",
  "protected_slice_non_degradation_status": "passed|failed",
  "holdout_status": "not_run|passed|failed",
  "canary_status": "not_required|pending|running|passed|failed",
  "rollback_pointer_ref": "sha256:...",
  "promotion_status": "candidate_recorded",
  "live_forecast_authority": false
}
```

## Phase 0: Anchor and Dependency Gate

Goal: prove Session 6 can start only the work whose upstream contracts are ready.

Pseudocode:

```python
owned = ["TRACE-002", "CAL-002", "CAL-003", "CAL-004", "CAL-005"]

for feature_id in owned:
    assert inventory.owner(feature_id) == "Session 6"

def gate(feature_id, mode):
    result = run(["python3", "plans/check_dependency_gates.py",
                  "--feature-id", feature_id, "--mode", mode])
    if mode != "fixture":
        assert result.status in ["OK", "BLOCKED"]
    return result

assert gate("CAL-002", "fixture").ok
assert gate("CAL-002", "autonomous_optimization_maturity").blocks_until(["CAL-001", "POL-001"])
```

Testing suite:

- Static: all owned rows exist in Markdown and machine-readable inventories.
- Static: `MIG-011` owner is Session 6.
- Gate: fixture mode allows maturity fixture work.
- Gate: autonomous optimization maturity blocks until `CAL-001` and `POL-001` are ready.
- Gate: dependency checker rejects cycles and unknown dependencies.

Checklist:

- [ ] Owned rows confirmed.
- [ ] Upstream blockers recorded.
- [ ] Feature inventory YAML and Markdown agree.
- [ ] Coverage map includes Session 6.

## Phase 1: Full Trace Materialization

Goal: expand minimal trace pointers into replayable, leak-safe trace materializations without live authority.

Implementation tasks:

- Consume Session 5 `training_trace_minimal` records.
- Load artifact manifests by hash and schema version.
- Materialize missing v2-specific candidate/correction records only when no canonical artifact exists.
- Preserve strict temporal isolation; never add post-resolution data to forecast-time inputs.
- Record materialization completeness, missing artifact refs, hash mismatches, and leak-safety validation.

Pseudocode:

```python
def materialize_full_trace(trace_id):
    trace = load_minimal_trace(trace_id)
    assert trace.live_authority == "none"
    artifacts = []
    for ref in trace.artifact_manifest_ids:
        manifest = load_manifest(ref)
        assert verify_hash(manifest.path, manifest.sha256)
        assert manifest.generated_at <= trace.forecast_timestamp or manifest.source_cutoff_timestamp <= trace.forecast_timestamp
        artifacts.append(manifest)
    full_trace = {
        "trace_id": trace_id,
        "materialization_id": make_id(trace_id, artifacts),
        "artifact_manifest_ids": [a.artifact_id for a in artifacts],
        "artifact_hashes": {a.artifact_id: a.sha256 for a in artifacts},
        "model_execution_contexts": trace.model_execution_contexts,
        "temporal_leak_check": "passed",
        "live_forecast_authority": False,
    }
    write_full_training_trace_materialization(full_trace)
    return full_trace
```

Testing suite:

- Unit: full trace rejects missing or changed artifact hash.
- Unit: full trace rejects post-forecast artifact as forecast input.
- Unit: full trace preserves decomposer and researcher model provenance.
- Unit: full trace has `live_forecast_authority=false`.
- Integration: fixture trace expands into a complete materialization record.

Checklist:

- [ ] Full trace materialization schema written.
- [ ] Temporal leak checks written.
- [ ] Hash mismatch errors are structured.
- [ ] `TRACE-002` inventory row updated with acceptance evidence.

## Phase 2: Calibration Lane Registry and Tunable Ownership

Goal: make tuning lanes explicit before any candidate policy is produced.

Implementation tasks:

- Load `POL-001` tunable registry.
- Define lane owners, bounds, risk tiers, promotion lane, canary rules, rollback semantics, and active pointer keys.
- Reject out-of-bounds candidates before scoring.
- Record lane health independently so one blocked lane does not block unrelated lanes when active pointers remain valid.

Pseudocode:

```python
def resolve_lane_registry(tunable_registry):
    lanes = {}
    for variable in tunable_registry.variables:
        lane = variable.owner_lane
        lanes.setdefault(lane, []).append(variable)
        assert variable.bounds is not None
        assert variable.risk_tier in ["low", "medium", "high", "emergency_conservative"]
        assert variable.rollback_semantics
    return lanes

def validate_candidate_bounds(candidate, lane_registry):
    for change in candidate.changed_parameters:
        spec = lane_registry.lookup(change.parameter_id)
        assert change.owner_lane == spec.owner_lane
        assert spec.min_value <= change.value <= spec.max_value
    return "passed"
```

Testing suite:

- Unit: unknown tunable variable rejected.
- Unit: wrong-owner lane rejected.
- Unit: out-of-bounds value rejected.
- Unit: missing rollback semantics rejected.
- Unit: unhealthy retrieval lane does not invalidate SCAE active pointer.

Checklist:

- [ ] Lane registry schema written.
- [ ] Active pointer key scheme written.
- [ ] Bounds validator written.
- [ ] Lane health record written.
- [ ] `CAL-002` inventory row updated.

## Phase 3: Replay Cohorts, Scorecards, and Component Diagnostics

Goal: score candidates against resolved cases without hiding component degradation.

Implementation tasks:

- Build replay cohorts by stage, regime, contract type, market-state tag, evidence environment, tail bucket, and actionability profile.
- Consume outcome/scoring records from Session 5.
- Compute Brier, log-loss, Adaptive Calibration Error, Brier reliability/resolution/uncertainty, Spiegelhalter Z, tail failure counts, and market baseline comparison.
- Produce component diagnostics across protected slices.
- Reject candidates that improve headline metrics while degrading protected slices beyond policy threshold.

Pseudocode:

```python
PROTECTED_SLICES = [
    "evidence_purpose",
    "source_class",
    "retrieval_quality_bucket",
    "market_prior_reliability_bucket",
    "market_state_regime_tag",
    "protected_primary_status",
    "family_aware_child_status",
    "missingness_no_catalyst_status",
    "claim_family_dependence_status",
]

def score_candidate(candidate, replay_cohort, policy):
    baseline = load_baseline_scorecard(replay_cohort)
    candidate_scores = replay_policy_candidate(candidate, replay_cohort)
    diagnostics = {}
    for slice_name in PROTECTED_SLICES:
        diagnostics[slice_name] = compare_slice(candidate_scores, baseline, slice_name)
        assert diagnostics[slice_name].degradation <= policy.max_protected_slice_degradation
    assert candidate_scores.tail_failures <= policy.max_tail_failures
    write_calibration_component_diagnostics(candidate, diagnostics)
    return candidate_scores
```

Testing suite:

- Unit: scorecard includes Brier, log-loss, ACE, Brier decomposition, Spiegelhalter Z, and tail failures.
- Unit: protected-slice degradation rejects candidate even when headline Brier improves.
- Unit: missing protected slice marks diagnostics incomplete.
- Unit: unresolved cases cannot enter resolved replay scoring.
- Integration: fixture replay produces scorecard and component diagnostics.

Checklist:

- [ ] Replay cohort selector written.
- [ ] Scorecard schema written.
- [ ] Protected component diagnostics written.
- [ ] Candidate non-degradation gate written.
- [ ] Diagnostics linked to `CAL-002`.

## Phase 4: Candidate Generation and Promotion Workflow

Goal: turn diagnostics into candidates, canaries, active pointers, and rollback events without live probability authority.

Implementation tasks:

- Generate bounded candidate policy snapshots.
- Require holdout and component non-degradation before canary.
- Require canary success before active pointer promotion when policy requires canary.
- Persist active pointer and rollback pointer atomically.
- Reject candidate promotion when base policy hash, lane owner, or bounds changed underneath.

Pseudocode:

```python
def promote_candidate(candidate, lane_policy):
    assert candidate.bounds_check_status == "passed"
    assert candidate.protected_slice_non_degradation_status == "passed"
    assert candidate.holdout_status == "passed"
    if lane_policy.canary_required:
        assert candidate.canary_status == "passed"
    current = load_active_pointer(candidate.lane_id)
    rollback_ref = current.policy_snapshot_ref
    promoted = {
        "lane_id": candidate.lane_id,
        "active_policy_snapshot_ref": candidate.policy_snapshot_ref,
        "candidate_id": candidate.candidate_id,
        "rollback_pointer_ref": rollback_ref,
        "promoted_at": now(),
    }
    promote_policy_pointer(promoted)
    write_policy_rollback_event(candidate, rollback_ref, reason="promotion")
```

Testing suite:

- Unit: candidate without diagnostics cannot promote.
- Unit: candidate with failed holdout cannot canary.
- Unit: failed canary cannot promote.
- Unit: active pointer promotion records rollback pointer.
- Unit: base policy file is not modified by candidate promotion.

Checklist:

- [ ] Candidate schema written.
- [ ] Canary state schema written.
- [ ] Active pointer write path written.
- [ ] Rollback event write path written.
- [ ] `MIG-011` row updated with destination tables or artifact contracts.

## Phase 5: Retrieval-Policy Calibration Lane

Goal: tune retrieval quality, expansion, source coverage, stale-evidence, and missingness policy using resolved replay.

Implementation tasks:

- Consume retrieval quality slices, claim families, protected-primary access status, missingness candidates, fallback status, and replay outcomes.
- Propose retrieval-policy snapshots only within registry bounds.
- Evaluate density, freshness, protected-source access, fallback effectiveness, and downstream SCAE sensitivity.
- Emit retrieval policy candidates and active pointer proposals through the generic lane workflow.

Pseudocode:

```python
def build_retrieval_policy_candidate(replay_results, registry):
    features = summarize_retrieval_performance(replay_results)
    proposal = {
        "lane_id": "retrieval_policy",
        "changed_parameters": bounded_retrieval_changes(features, registry),
        "reason_codes": features.failure_modes,
    }
    validate_candidate_bounds(proposal, registry)
    score_candidate(proposal, replay_results.cohort, registry.policy)
    write_retrieval_policy_snapshot(proposal)
```

Testing suite:

- Unit: thin retrieval penalty proposal requires enough resolved cases in thin bucket.
- Unit: stale-evidence tuning cannot use post-forecast source observations.
- Unit: protected-primary failure metrics are separated from generic missingness.
- Unit: retrieval candidate with worse protected-primary coverage is rejected.

Checklist:

- [ ] Retrieval policy candidate schema written.
- [ ] Retrieval replay features written.
- [ ] Protected-primary diagnostics written.
- [ ] `CAL-003` inventory row updated.

## Phase 6: Decomposer, Profile, and Decision/Actionability Lanes

Goal: tune decomposition profile, effective tuning profile, and actionability policy without allowing live LLMs or Decision-Maker to choose numeric weights.

Implementation tasks:

- Use decomposer validation outcomes, decomposer-miss labels, QDT shapes, branch/leaf counts, AMRG usage, and SCAE outcomes to evaluate decomposer profiles.
- Use decision/actionability outcomes to evaluate watch-only, low-size-only, needs-refresh, and forbidden routing.
- Use effective profile contexts to test conservative overlays and domain/profile matching.
- Produce candidate profile snapshots with owner lane, active pointer key, and protected component diagnostics.

Pseudocode:

```python
def evaluate_profile_candidate(candidate, replay_cohort):
    assert candidate.lane_id in [
        "decomposer_profile",
        "decision_actionability_profile",
        "effective_tuning_profile",
    ]
    assert not candidate.created_by_live_llm
    results = replay_profile(candidate, replay_cohort)
    assert no_probability_override(results)
    assert protected_slice_non_degradation(results)
    return write_decomposer_profile_candidate(candidate) if candidate.lane_id == "decomposer_profile" else write_decision_actionability_candidate(candidate)
```

Testing suite:

- Unit: decomposer profile candidate records QDT shape and miss-label effects.
- Unit: decision/actionability candidate cannot alter probability.
- Unit: unpromoted effective profile overlay cannot apply live.
- Unit: profile candidate with family-aware child degradation is rejected.

Checklist:

- [ ] Decomposer profile candidate schema written.
- [ ] Decision/actionability candidate schema written.
- [ ] Effective profile candidate schema written.
- [ ] `CAL-004` inventory row updated.

## Phase 7: Emergency Conservative Overlay

Goal: allow autonomous risk reduction while preserving non-authority boundaries.

Implementation tasks:

- Define emergency overlay eligibility from catastrophic tail checks, severe component degradation, or stale active pointer health.
- Limit overlays to risk-reducing actions: wider intervals, lower caps, watch-only/low-size-only routing, conservative tail caps, or stricter freshness gates.
- Require expiry, owner lane, reason codes, and rollback semantics.
- Forbid emergency overlays from increasing confidence or authoring probability replacements.

Pseudocode:

```python
def build_emergency_overlay(trigger, policy):
    assert trigger.kind in policy.allowed_emergency_triggers
    overlay = {
        "lane_id": "emergency_conservative_overlay",
        "reason_codes": trigger.reason_codes,
        "effects": conservative_effects_only(trigger),
        "expires_at": now() + policy.max_overlay_ttl,
        "rollback_semantics": "expire_or_manual_policy_pointer_rollback",
    }
    assert all(effect.direction in ["reduce_confidence", "widen_interval", "downgrade_actionability"] for effect in overlay["effects"])
    write_emergency_conservative_overlay(overlay)
```

Testing suite:

- Unit: overlay that tightens interval is rejected.
- Unit: overlay without expiry is rejected.
- Unit: overlay cannot replace SCAE probability.
- Unit: rollback event is recorded on expiry or supersession.

Checklist:

- [ ] Emergency overlay schema written.
- [ ] Conservative-effect validator written.
- [ ] Expiry and rollback tests written.
- [ ] Lane health integration written.

## Phase 8: Autonomous Optimization Maturity Gate

Goal: decide when the optimization lane is mature enough to operate continuously without weakening cutover safety.

Implementation tasks:

- Require successful full trace materialization for configured cohorts.
- Require lane registry coverage for all promoted tunables.
- Require stable active pointers over configured recent-dispatch window.
- Require zero catastrophic tail failures above policy confidence threshold.
- Require component diagnostics and rollback readiness for each active lane.
- Record maturity result without changing live cutover status by itself.

Pseudocode:

```python
def optimization_maturity_gate(state, policy):
    checks = {
        "full_trace_materialization": state.full_trace_completion >= policy.min_trace_completion,
        "lane_registry_coverage": state.registry_coverage == "complete",
        "active_pointer_stability": state.pointer_stability_window >= policy.min_stability_window,
        "catastrophic_tail_failures": state.catastrophic_tail_failures == 0,
        "component_diagnostics": state.all_active_lanes_have_component_diagnostics,
        "rollback_ready": state.all_active_lanes_have_rollback_pointers,
    }
    status = "passed" if all(checks.values()) else "blocked"
    write_optimization_maturity_result(status=status, checks=checks)
    return status
```

Testing suite:

- Unit: missing full trace materialization blocks maturity.
- Unit: missing rollback pointer blocks maturity.
- Unit: unstable active pointer blocks maturity.
- Unit: catastrophic tail failure blocks maturity.
- Unit: maturity result does not change live forecast authority.

Checklist:

- [ ] Maturity gate schema written.
- [ ] Maturity checks implemented or specified.
- [ ] Maturity result write path is non-authoritative.
- [ ] `CAL-005` inventory row updated.

## End-to-End Completion Checklist

- [ ] Session 6 ownership is reflected in Markdown inventory, YAML inventory, coverage map, and master plan.
- [ ] Dependency gate blocks runtime maturity work until upstream rows are ready or waived.
- [ ] Full trace materialization is leak-safe and non-authoritative.
- [ ] `MIG-011` has table/schema/artifact contracts for candidate, diagnostics, canary, active pointer, rollback, and lane health records.
- [ ] Component diagnostics protect evidence purpose, source class, retrieval quality, market-prior reliability, regime, protected primary, family-aware child status, missingness/no-catalyst, and claim-family/dependence slices.
- [ ] Candidate promotion requires bounds, holdout, component non-degradation, canary when required, active pointer write, and rollback pointer.
- [ ] Retrieval, decomposer/profile, and decision/actionability lanes are separate and lane-owned.
- [ ] Emergency overlays are conservative only and expiring.
- [ ] Autonomous optimization maturity result is recorded without creating a live forecast path.
