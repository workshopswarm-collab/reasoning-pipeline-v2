# Session 05 Plan: SCAE, Synthesis/Decision Handoff, and Evaluator Spine

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

- Section 1.1: live forecast authority, probability fields, direct-cutover hardening.
- Section 3.7 to 3.9: SCAE, synthesis, decision.
- Section 10 and 10.1: ledger, calibration, replay, and training trace persistence.
- Section 11: SCAE specification.
- Section 12: synthesis contract changes.
- Section 13: Decision-Maker role and contract changes.
- Section 14 and 15: failure semantics and autonomy requirements.
- Section 16: configuration summary.
- Section 17.1: SCAE, synthesis, decision, forecast persistence, evaluator migration surfaces.
- Section 18: cutover, calibration debt clearance, and maturity gates.

## Mission

Implement the only live numeric forecast authority: SCAE. Then gate synthesis and decision so neither can replace SCAE probability. Add minimal non-authoritative trace/replay records for calibration debt and future autonomous optimization.

This session must not build a second live forecast path, allow researcher/synthesis/decision probability authoring, or clear calibration debt from first-100 trace completeness alone.

## Runtime Script Placement

Session 5 deterministic ledger work belongs to SCAE under `/Users/agent2/.openclaw/SCAE/scripts`. Orchestrator keeps only post-SCAE routing, synthesis annotation, decision/actionability, and pipeline persistence handoff scripts under `/Users/agent2/.openclaw/orchestrator/scripts`. Add any new path to `plans/autonomous-decomposition-swarm-script-placement-map.md` before implementation.

Planned SCAE paths:

```text
/Users/agent2/.openclaw/SCAE/scripts/bin/run_scae_ledger.py
/Users/agent2/.openclaw/SCAE/scripts/bin/validate_scae_ledger.py
/Users/agent2/.openclaw/SCAE/scripts/bin/persist_scae_forecast.py
/Users/agent2/.openclaw/SCAE/scripts/bin/report_scae_scorecard.py
/Users/agent2/.openclaw/SCAE/scripts/scae/ledger.py
/Users/agent2/.openclaw/SCAE/scripts/scae/policy.py
/Users/agent2/.openclaw/SCAE/scripts/scae/netting.py
/Users/agent2/.openclaw/SCAE/scripts/scae/intervals.py
/Users/agent2/.openclaw/SCAE/scripts/scae/persistence.py
```

Planned Orchestrator post-SCAE paths:

```text
/Users/agent2/.openclaw/orchestrator/scripts/bin/run_synthesis_annotation.py
/Users/agent2/.openclaw/orchestrator/scripts/bin/run_decision_gate.py
```

Ownership boundaries:

- SCAE scripts must be deterministic and must not call live LLMs, conduct research, or wake researcher agents.
- Orchestrator may call SCAE and route its output, but it must not reauthor probability fields or intervals.
- Forecast persistence uses only SCAE `production_forecast_prob` and the prediction-time market snapshot provenance from the ADS case contract.

## Owned Inventory Rows

Directly owned rows:

- `SCAE-001`: base policy and probability taxonomy.
- `SCAE-002`: prior odds and market-assimilation context.
- `SCAE-003`: evidence delta mapping.
- `SCAE-004`: correlated-quality guard and cap stack.
- `SCAE-005`: intra-leaf representative cluster netting.
- `SCAE-006`: cross-leaf dependence guard.
- `SCAE-007`: branch sub-ledgers.
- `SCAE-008`: missingness and survival/no-catalyst policy.
- `SCAE-009`: binary-child diagnostics and displacement signals.
- `SCAE-010`: conditional branch recombination.
- `SCAE-011`: deterministic logit interval builder.
- `SCAE-012`: identity calibration and debt controls.
- `SCAE-013`: research sufficiency certificate intake and forecast-validity guard.
- `SYN-001`: qualitative annotation only.
- `DEC-001`: Decision/Execution Gate consumes SCAE probability only.
- `PERSIST-001`: production forecast persistence from SCAE only.
- `PERSIST-002`: existing prediction scoring bridge into `market_predictions`.
- `TRACE-001`: synchronous minimal trace pointer.
- `MODEL-004`: model provenance trace.
- `REPLAY-001`: first-100 replay manifests and result records.
- `SCORE-001`: Brier scoring and prediction-time market baseline comparison.
- `CAL-001`: explicit debt-clearance gates.

Downstream handoff rows owned by Session 6:

- `TRACE-002`: async full trace materialization.
- `CAL-002`: lane queues, pointers, canaries, health, rollback.
- `CAL-003`: retrieval-policy calibration snapshots.
- `CAL-004`: decomposer and decision/actionability profile lanes.
- `CAL-005`: autonomous optimization maturity gate.

## Coordination Rules

1. Update only Session 5 rows directly.
2. Do not mark `SCAE-003` integration-ready until `VER-001`, `VER-002`, and `RET-003` are ready.
3. Do not mark `SCAE-005` or `SCAE-006` integration-ready until `RET-004` is ready.
4. Do not mark `SCAE-010` integration-ready until `AMRG-008`, `QDT-004`, and `SCAE-007` are ready.
5. Do not mark `SCAE-013` integration-ready until `VER-004` and `SCAE-011` are ready.
6. Do not mark `SCAE-012` integration-ready until `SCAE-013` is ready.
7. Do not mark `SYN-001`, `DEC-001`, or `PERSIST-001` ready until `SCAE-012` is ready.
8. Do not mark `PERSIST-002` ready until `PERSIST-001` and `CASE-002` are ready.
9. Do not mark `SCORE-001` ready until `PERSIST-002` and `REPLAY-001` are ready.
10. Do not mark `CAL-001` ready until `SCORE-001`, `REPLAY-001`, and `SCAE-012` are ready.
11. Do not mark `MODEL-004` ready until `MODEL-002`, `MODEL-003`, and `TRACE-001` are ready.
12. Do not edit Session 6 maturity rows directly. If SCAE exposes new tuning facts, add a handoff note or proposed inventory change for Session 6.
13. Maturity rows (`TRACE-002`, `CAL-002` to `CAL-005`) must not block v2 live cutover unless the master plan or inventory explicitly reclassifies them.
14. Any field needed from other sessions must be proposed in the inventory and negotiated before runtime integration.

## Migration and Write Path Ownership

Session 5 owns `MIG-007`, `MIG-008`, `MIG-009` minimal trace/replay records, and `MIG-010`. Runtime integration of SCAE and decision is blocked until `MIG-007` and `MIG-008` have destination tables, schemas, or explicit artifact contracts. Calibration-debt clearance is blocked until `MIG-009` and `MIG-010` are operational. Session 6 owns `MIG-011` and contributes `TRACE-002` full trace materialization against the `MIG-009` trace/replay contract after Session 5 has produced minimal traces and replay manifests.

Required write paths:

```text
write_scae_ledger
write_scae_log_odds_update_slices
write_scae_branch_subledger_slices
write_scae_conditional_branch_slices
write_scae_calibration_diagnostic_slices
write_scae_research_sufficiency_inputs
write_forecast_decision
record_market_prediction
record_prediction_with_snapshot
write_minimal_training_trace
write_replay_manifest
write_resolution_score
settle_market_outcome
brier_score_report
write_evaluator_scorecard
```

`write_scae_ledger` is the most important future tuning surface. It must store the prior, market-prior reliability context, every signed log-odds update, cap stack, quality multipliers before and after correlated-quality guard, intra-leaf netting, cross-leaf dependence, branch sub-ledgers, family diagnostics, conditional branch audit, research sufficiency certificate refs, retrieval breadth profile/coverage refs, readiness decisions, interval builder inputs, calibration context, calibration-debt context, and final probability fields.

`write_forecast_decision` must persist only SCAE `production_forecast_prob` and the decision/actionability status. `record_market_prediction()` and `record_prediction_with_snapshot()` bridge that same SCAE production probability into the existing `market_predictions` scoring spine with prediction-time market snapshot provenance from `ads-case-contract/v1`. `write_resolution_score`, `settle_market_outcome()`, and `brier_score_report()` must join forecasts to resolved outcomes and record Brier, market baseline Brier, Brier edge, scoring version, resolution provenance, log-loss where available, and evaluator reliability bucket where available. Session 5 may write evaluator scorecards needed for calibration-debt clearance, but maturity calibration candidates, canaries, active pointers, rollback pointers, and lane-health records are Session 6 write paths under `MIG-011`.

## Technical Specification

### Probability Field Contract

SCAE must emit:

```text
raw_ledger_probability
post_ledger_probability
debt_adjusted_probability
production_forecast_prob
canonical_probability
```

Rules:

- `raw_ledger_probability` is posterior log-odds converted to probability before post-ledger calibration.
- `post_ledger_probability` is after identity or live-eligible calibration and before debt controls.
- `debt_adjusted_probability` is after calibration-debt tail caps or conservative controls.
- `production_forecast_prob` is the only production forecast persistence value.
- `canonical_probability` is an artifact-facing alias for `production_forecast_prob`, not pre-debt calibrated probability.

### SCAE Ledger Skeleton

```json
{
  "artifact_type": "scae_ledger",
  "schema_version": "scae-ledger/v1",
  "case_id": "case-...",
  "dispatch_id": "dispatch-...",
  "prior_context": {},
  "market_prior_assimilation_context": {},
  "evidence_update_slices": [],
  "cluster_netting_summary": {},
  "cross_leaf_dependence_summary": {},
  "branch_subledger_summary": {},
  "family_diagnostics": {},
  "conditional_branch_summary": {},
  "research_sufficiency_context": {
    "bundle_status": "scae_ready_high_certainty|watch_only_structurally_unanswerable|invalid_insufficient_research",
    "leaf_certificate_refs": [],
    "leaf_reconciliation_refs": [],
    "leaf_escalation_decision_refs": [],
    "blocked_leaf_ids": [],
    "structurally_unanswerable_leaf_ids": []
  },
  "calibration_context": {},
  "calibration_debt_context": {},
  "interval": {},
  "raw_ledger_probability": 0.5,
  "post_ledger_probability": 0.5,
  "debt_adjusted_probability": 0.5,
  "production_forecast_prob": 0.5,
  "canonical_probability": 0.5,
  "forecast_validity_status": "valid_for_forecast|valid_for_forecast_watch_only|invalid_for_forecast",
  "execution_authority_status": "normal_execution_allowed|low_size_only|watch_only|needs_refresh|forbidden"
}
```

## Phase 0: Anchor and Dependency Gate

Goal: confirm Session 5 ownership and dependency posture.

Pseudocode:

```python
owned = ["SCAE-001", "SCAE-002", "SCAE-003", "SCAE-004", "SCAE-005", "SCAE-006",
         "SCAE-007", "SCAE-008", "SCAE-009", "SCAE-010", "SCAE-011", "SCAE-012", "SCAE-013",
         "SYN-001", "DEC-001", "PERSIST-001", "PERSIST-002", "TRACE-001", "MODEL-004",
         "REPLAY-001", "SCORE-001", "CAL-001"]

for feature_id in owned:
    assert inventory.owner(feature_id) == "Session 5"

handoff = ["TRACE-002", "CAL-002", "CAL-003", "CAL-004", "CAL-005"]
for feature_id in handoff:
    assert inventory.owner(feature_id) == "Session 6"

if mode == "runtime_integration":
    assert_done("FND-004")
    assert_done("POL-003")
    assert_done("VER-001")
    assert_done("VER-002")
    assert_done("VER-004")
    assert_done("RET-003")
```

Tests:

- Static: all owned rows exist and are owned by Session 5.
- Static: maturity handoff rows exist and are owned by Session 6.
- Gate: SCAE integration blocks without verified classifications.
- Gate: synthesis/decision integration blocks without SCAE probability taxonomy.

Checklist:

- [ ] Active rows marked `in_progress`.
- [ ] Fixture or runtime mode declared.
- [ ] Missing upstream blockers recorded.

## Phase 1: SCAE Policy and Probability Taxonomy

Goal: define SCAE runtime policy and output probability contract before math modules.

Implementation tasks:

- Define `scae-policy.json` base schema.
- Define default identity post-ledger calibration.
- Define calibration-debt active defaults.
- Define cap stack policy variables.
- Define probability field taxonomy.
- Define validity and execution authority separation.

Pseudocode:

```python
def resolve_scae_policy(base_policy, effective_profile_context, active_pointers):
    policy = merge_policy(
        base=base_policy,
        profile_slice=effective_profile_context.subsystem_policy_slices["scae"],
        active_calibration=active_pointers.scae_calibration,
        emergency_overlay=active_pointers.emergency_conservative_overlay,
    )
    assert policy.post_ledger_calibration.default_method == "identity"
    assert policy.calibration_debt_mode.active in [True, False]
    return policy

def validate_probability_taxonomy(ledger):
    assert ledger.production_forecast_prob == (
        ledger.debt_adjusted_probability if ledger.calibration_debt_context.active
        else ledger.post_ledger_probability
    )
    assert ledger.canonical_probability == ledger.production_forecast_prob
```

Testing suite:

- Unit: policy defaults to identity calibration.
- Unit: calibration-debt active means production equals debt-adjusted.
- Unit: calibration-debt cleared means production equals post-ledger.
- Unit: canonical probability aliases production only.
- Unit: Decision status cannot upgrade SCAE validity.

Completion checklist:

- [ ] Policy schema written.
- [ ] Probability taxonomy tests written.
- [ ] Validity/execution authority split written.
- [ ] `SCAE-001` inventory row updated.

## Phase 2: Prior Odds and Market-Assimilation Context

Goal: establish prior log-odds with reliability/shrinkage rules before evidence deltas.

Implementation tasks:

- Use market live probability when valid.
- Fall back to validated historical/base-rate prior only when pre-ledger provider materializes it.
- Fall back to neutral only when no valid market or structural prior exists.
- Compute prior reliability from rolling microstructure inputs.
- Shrink unreliable market priors toward validated structural/base-rate prior or neutral fallback.
- Compute market-assimilation discount and orthogonality context for public/base-rate/time-passage evidence.

Pseudocode:

```python
def compute_adjusted_prior(prior_input, structural_prior, policy):
    raw_p = clamp(prior_input.probability, policy.epsilon, 1 - policy.epsilon)
    raw_log_odds = logit(raw_p)
    reliability = compute_prior_reliability(prior_input.microstructure, policy)
    if structural_prior.valid:
        shrink_target = logit(structural_prior.probability)
        target_type = "structural_base_rate"
    else:
        shrink_target = 0.0
        target_type = "neutral_default"
    adjusted = reliability * raw_log_odds + (1 - reliability) * shrink_target
    return PriorContext(raw_log_odds, reliability, target_type, adjusted)

def market_assimilation_discount(evidence, prior_context, policy):
    if prior_context.source != "market_live_probability":
        return 1.0
    if evidence.published_at > prior_context.market_snapshot_timestamp:
        return 1.0
    if evidence.publicness == "public" and prior_context.reliability_class == "fresh_liquid":
        return policy.public_old_evidence_discount
    return policy.discount_floor
```

Testing suite:

- Unit: invalid market prior falls back to validated structural prior.
- Unit: no structural prior falls back to neutral with uncertainty flags.
- Unit: fresh liquid market cannot be shrunk below configured floor without contradiction/spoofing.
- Unit: stale thin market cannot retain reliability above configured ceiling.
- Unit: old public evidence in liquid market receives assimilation discount.
- Unit: base-rate evidence matching shrinkage anchor gets zero signed delta.

Completion checklist:

- [ ] Prior context implemented or specified.
- [ ] Market-assimilation context implemented or specified.
- [ ] Structural prior overlap rules written.
- [ ] `SCAE-002` inventory row updated.

## Phase 3: Evidence Delta Mapping, Quality Guard, and Cap Stack

Goal: convert verified classification rows into bounded signed log-odds candidates.

Implementation tasks:

- Map impact direction and evidence strength to raw score.
- Apply verified direction multiplier.
- Apply evidence-quality multiplier after quality verification.
- Apply retrieval-quality, temporal-state, temporal-decay, market-assimilation, orthogonality, regime-aware, and persona reliability multipliers where policy allows.
- Apply correlated-quality guard.
- Apply per-update cap.

Pseudocode:

```python
def evidence_delta(row, policy_context):
    signed_strength = strength_to_log_odds(row.evidence_strength, policy_context)
    direction = verified_direction_multiplier(row.direction_verification)
    raw_quality = quality_product(row.quality_verification.accepted_quality_fields)
    final_quality = apply_correlated_quality_guard(
        raw_quality,
        row.quality_verification.quality_correlation_groups,
        policy_context,
    )
    multiplier = (
        direction
        * final_quality
        * retrieval_quality_multiplier(row.retrieval_quality)
        * temporal_multiplier(row.temporal_state)
        * market_assimilation_discount(row)
        * market_prior_orthogonality_multiplier(row)
        * regime_weighting_multiplier(row)
    )
    pre_cap_delta = signed_strength * multiplier
    return cap(pre_cap_delta, policy_context.per_update_cap)
```

Testing suite:

- Unit: unverified non-neutral row rejected.
- Unit: missing quality verification rejected.
- Unit: correlated-quality guard lowers excessive multiplier.
- Unit: public evidence discount applied under market prior.
- Unit: per-update cap enforced.
- Regression: duplicate citations do not add force here.

Completion checklist:

- [ ] Evidence delta mapping written.
- [ ] Correlated-quality guard written.
- [ ] Cap stack starts with per-update cap.
- [ ] `SCAE-003` and `SCAE-004` inventory rows updated.

## Phase 4: Intra-Leaf Netting and Cross-Leaf Dependence

Goal: prevent duplicate same-claim force within and across leaves.

Implementation tasks:

- Group by `event_source_family + claim_family_id`.
- Select bounded representative positive and negative contributions per sign.
- Record corroboration and contradiction metadata separately.
- Apply source-class caps and cluster caps.
- Allocate same-claim reuse across leaves through shared-claim union.
- Record same-mechanism distinct-claim markers as dependence/interval effects, not default evidence force.

Pseudocode:

```python
def net_leaf_updates(update_candidates):
    clusters = group_by(update_candidates, key=lambda u: (u.event_source_family, u.claim_family_id))
    leaf_delta = 0.0
    slices = []
    for cluster_key, updates in clusters.items():
        pos = select_representative([u for u in updates if u.delta > 0], sign="positive")
        neg = select_representative([u for u in updates if u.delta < 0], sign="negative")
        contribution = cap_cluster(sum([pos.delta if pos else 0, neg.delta if neg else 0]))
        slices.append(record_cluster_slice(cluster_key, pos, neg, contribution, updates))
        leaf_delta += contribution
    return leaf_delta, slices

def apply_cross_leaf_dependence(leaf_slices):
    claim_groups = group_by_claim_family_across_leaves(leaf_slices)
    return shared_claim_union_allocation(claim_groups)
```

Testing suite:

- Unit: repeated same claim across citations contributes once by default.
- Unit: positive and negative representative contributions can both be recorded.
- Unit: comprehensive official source can contribute distinct claim families.
- Unit: same-mechanism distinct claims reduce independence but do not merge as same claim.
- Unit: source-class and cluster caps enforced.

Completion checklist:

- [ ] Intra-leaf netting written.
- [ ] Corroboration metadata separated from posterior force.
- [ ] Cross-leaf dependence guard written.
- [ ] `SCAE-005` and `SCAE-006` inventory rows updated.

## Phase 5: Branch Sub-Ledgers, Temporal/Missingness, and Family Diagnostics

Goal: handle expanded decompositions, missingness, time passage, and family-aware child context.

Implementation tasks:

- Use branch sub-ledgers when QDT requires hierarchical branch ledger.
- Apply sign-partitioned covariance penalties before branch netting.
- Apply survival/no-catalyst adjustment only when hazard family, source coverage, and unpriced interval permit it.
- Apply signed missingness only with explicit mechanism proof.
- Prevent missingness and no-catalyst double counting without distinct mechanism proof.
- Persist family displacement signals and consistency diagnostics without sibling evidence deltas.

Pseudocode:

```python
def build_branch_subledgers(leaf_deltas, qdt, policy):
    branches = group_by(leaf_deltas, key=lambda l: l.parent_branch_id)
    output = []
    for branch_id, leaves in branches.items():
        pos_vector = [l.delta for l in leaves if l.delta > 0]
        neg_vector = [l.delta for l in leaves if l.delta < 0]
        pos_penalty = covariance_penalty(pos_vector, branch_id, sign="positive")
        neg_penalty = covariance_penalty(neg_vector, branch_id, sign="negative")
        branch_delta = sum(pos_vector) * pos_penalty + sum(neg_vector) * neg_penalty
        output.append(record_branch_subledger(branch_id, branch_delta))
    return output

def survival_no_catalyst_delta(context):
    if not context.hazard_family_allowed:
        return zero_delta("hazard_family_lockout")
    if not context.source_coverage_sufficient:
        return zero_delta("source_coverage_insufficient")
    interval = unpriced_interval(context.market_priced_through_timestamp, context.forecast_timestamp)
    return hazard_delta(interval, context.hazard_schedule)
```

Testing suite:

- Unit: expanded decomposition uses branch sub-ledgers, not flat summation.
- Unit: branch covariance applies sign-partitioned penalties.
- Unit: scheduled point-deadline market does not get generic continuous decay.
- Unit: missingness plus no-catalyst overlap rejected without distinct proof.
- Unit: sibling prices do not create SCAE evidence updates.

Completion checklist:

- [ ] Branch sub-ledger logic written.
- [ ] Missingness and survival policy written.
- [ ] Family diagnostics written.
- [ ] `SCAE-007`, `SCAE-008`, and `SCAE-009` inventory rows updated.

## Phase 6: Conditional AMRG Branch Recombination

Goal: support strict-precedence AMRG prior anchors only through valid condition-scoped branch math.

Implementation tasks:

- Require validated AMRG strict-precedence anchor.
- Require QDT anchor dependency contract and condition-scoped leaves.
- Require adjusted upstream probability and reliability context.
- Build separate `target_given_upstream` and `target_given_not_upstream` branch sub-ledgers.
- Recombine as `P(selected|upstream)P(upstream) + P(selected|not upstream)P(not upstream)`.
- Reject unconditional selected-market prior reuse as both branch priors.
- Follow QDT fallback/repair contract when validation fails.

Pseudocode:

```python
def conditional_recombination(qdt_contract, amrg_anchor, branch_ledgers):
    if not amrg_anchor.validated_strict_precedence:
        return reject_or_fallback("anchor_not_validated", qdt_contract)
    assert qdt_contract.has_condition_scoped_leaves
    assert amrg_anchor.adjusted_upstream_probability is not None

    up = build_condition_branch_probability(
        branch_ledgers["target_given_upstream"],
        prior_source=qdt_contract.upstream_branch_prior_source,
    )
    not_up = build_condition_branch_probability(
        branch_ledgers["target_given_not_upstream"],
        prior_source=qdt_contract.not_upstream_branch_prior_source,
    )
    assert up.selected_market_prior_used_in_branch in [False, "diagnostic_only"]
    assert not_up.selected_market_prior_used_in_branch in [False, "diagnostic_only"]

    p_upstream = amrg_anchor.adjusted_upstream_probability
    return up.probability * p_upstream + not_up.probability * (1 - p_upstream)
```

Testing suite:

- Unit: weak/context-only edge rejected.
- Unit: cyclic/concurrent edge rejected.
- Unit: missing condition-scoped leaves rejected.
- Unit: selected market prior reused as both branch priors rejected.
- Unit: repair budget exhaustion follows QDT policy and does not loop.

Completion checklist:

- [ ] Conditional branch validation written.
- [ ] Recombination math written.
- [ ] Prior reuse rejection written.
- [ ] Fallback/repair behavior written.
- [ ] `SCAE-010` inventory row updated.

## Phase 7: Interval Builder and Pre-Debt Ledger Output

Goal: produce pre-debt SCAE probabilities and interval inputs before final sufficiency and calibration-debt controls.

Implementation tasks:

- Sum adjusted prior and evidence/branch deltas.
- Convert posterior log-odds to raw ledger probability.
- Apply identity-by-default post-ledger calibration.
- Build deterministic logit uncertainty interval.
- Record cap stack and calibration context.

Pseudocode:

```python
def finalize_ledger(adjusted_prior_log_odds, branch_deltas, policy):
    posterior_log_odds = adjusted_prior_log_odds + sum(branch_deltas)
    raw = sigmoid(posterior_log_odds)
    post = apply_post_ledger_calibration(raw, policy.post_ledger_calibration)
    interval = build_logit_uncertainty_interval(
        post_logit=logit(post),
        width_components=collect_width_components(),
        policy=policy.interval_policy,
    )
    return Ledger(raw_ledger_probability=raw, post_ledger_probability=post, interval=interval)
```

Testing suite:

- Unit: identity calibration preserves raw probability.
- Unit: interval widens from low retrieval quality and dependence penalties.
- Unit: all probability fields are bounded in `[0, 1]`.

Completion checklist:

- [ ] Ledger finalization written.
- [ ] Interval builder written.
- [ ] `SCAE-011` inventory row updated.

## Phase 8: Research Sufficiency Intake and Forecast-Validity Guard

Goal: ensure SCAE only produces a live-valid forecast from high-certainty research, while preserving structurally unanswerable or insufficient research as explicit non-clean states.

Implementation tasks:

- Load Session 4 `VER-004` reconciliation slices.
- Require every SCAE-bound leaf to be `scae_ready_high_certainty` or policy-valid `structurally_unanswerable`.
- Require every `scae_ready_high_certainty` leaf to carry retrieval breadth profile and coverage refs from `RET-009`; SCAE does not reclassify source/claim/source-family breadth itself.
- Require Session 4 reconciliation to have resolved any required `researcher-escalation-decision/v1`; SCAE does not create extra researcher assignments itself.
- Set `forecast_validity_status=invalid_for_forecast` when any required leaf is `blocked_insufficient_research`.
- Set `valid_for_forecast_watch_only` only when policy permits structurally unanswerable leaves after full expansion proof.
- Persist certificate refs, reconciliation refs, escalation decision refs, blocked leaves, structurally unanswerable leaves, and sufficiency policy snapshot IDs.
- Add insufficiency components to interval/debug context, but never transform uncertified thin research into ordinary weak evidence.

Pseudocode:

```python
def apply_research_sufficiency_guard(ledger, qdt, sufficiency_reconciliations, policy):
    status_by_leaf = {r.leaf_id: r.reconciled_status for r in sufficiency_reconciliations}
    blocked = []
    structurally_unanswerable = []
    for leaf in qdt.required_leaf_questions:
        status = status_by_leaf.get(leaf.leaf_id)
        if status == "scae_ready_high_certainty":
            continue
        if status == "structurally_unanswerable" and policy.allow_watch_only_structural_unanswerability:
            structurally_unanswerable.append(leaf.leaf_id)
            continue
        blocked.append(leaf.leaf_id)

    ledger.research_sufficiency_context = {
        "bundle_status": "invalid_insufficient_research" if blocked else (
            "watch_only_structurally_unanswerable" if structurally_unanswerable else "scae_ready_high_certainty"
        ),
        "leaf_reconciliation_refs": [r.research_sufficiency_reconciliation_id for r in sufficiency_reconciliations],
        "leaf_breadth_profile_refs": [r.retrieval_breadth_profile_ref for r in sufficiency_reconciliations if r.retrieval_breadth_profile_ref],
        "leaf_breadth_coverage_refs": [r.retrieval_breadth_coverage_ref for r in sufficiency_reconciliations if r.retrieval_breadth_coverage_ref],
        "leaf_escalation_decision_refs": [r.escalation_decision_ref for r in sufficiency_reconciliations if r.escalation_decision_ref],
        "blocked_leaf_ids": blocked,
        "structurally_unanswerable_leaf_ids": structurally_unanswerable,
    }
    if blocked:
        ledger.forecast_validity_status = "invalid_for_forecast"
    elif structurally_unanswerable:
        ledger.forecast_validity_status = "valid_for_forecast_watch_only"
    return ledger

def apply_calibration_debt_controls_after_sufficiency(ledger, policy):
    if ledger.forecast_validity_status == "invalid_for_forecast":
        return ledger
    debt = apply_calibration_debt_controls(ledger.post_ledger_probability, policy.calibration_debt)
    ledger.debt_adjusted_probability = debt
    ledger.production_forecast_prob = debt if policy.calibration_debt.active else ledger.post_ledger_probability
    ledger.canonical_probability = ledger.production_forecast_prob
    return ledger
```

Testing suite:

- Unit: missing `VER-004` reconciliation marks ledger invalid.
- Unit: blocked insufficient research prevents production forecast validity.
- Unit: structurally unanswerable leaf can only become watch-only when policy permits.
- Unit: high-certainty bundle permits normal debt-control finalization.
- Unit: uncertified thin research cannot be converted into weak SCAE evidence.
- Unit: ledger records certificate/reconciliation/breadth refs for replay and tuning.

Completion checklist:

- [ ] Research sufficiency context schema written.
- [ ] Sufficiency guard implemented or specified.
- [ ] Invalid/watch-only transition rules written.
- [ ] Calibration-debt finalization waits on sufficiency guard.
- [ ] `SCAE-013` and `SCAE-012` inventory rows updated.

## Phase 9: Synthesis, Decision, and Forecast Persistence Gates

Goal: enforce SCAE as the only numeric authority after ledger creation and persist a scoreable prediction-time market baseline.

Implementation tasks:

- Synthesis prompt consumes SCAE ledger and asks for qualitative annotation only.
- Synthesis validation rejects replacement probability ranges or fair values.
- Decision context uses SCAE `production_forecast_prob` and `canonical_probability`.
- Decision may downgrade execution but cannot upgrade forecast validity or replace probability.
- Forecast persistence writes only SCAE production forecast probability.
- Forecast persistence writes the same probability to the existing `market_predictions` benchmark path using the ADS case contract snapshot binding.
- If the selected prediction-time snapshot is missing or stale, either atomically record a fresh market snapshot with the prediction or block scoreable persistence with a structured error.
- Persist `prediction_run_id`, `forecast_artifact_id`, `case_key`, `case_id`, `dispatch_id`, SCAE artifact path/hash, snapshot ID, source payload hash, market baseline probability, market baseline method, snapshot age, and scoring provenance fields.

Pseudocode:

```python
def build_synthesis_bundle(scae_ledger, classification_matrix):
    return {
        "macro_question": scae_ledger.macro_question,
        "classification_matrix": classification_matrix.summary,
        "scae_ledger_summary": scae_ledger.summary,
        "allowed_outputs": ["qualitative_annotation", "blockers", "rerun_recommendations"],
        "forbidden_outputs": ["probability", "fair_value", "interval_override"],
    }

def validate_decision_packet(packet, scae_ledger):
    assert packet.forecast_prob == scae_ledger.production_forecast_prob
    assert packet.canonical_probability == scae_ledger.canonical_probability
    assert not contains_replacement_probability(packet)
    assert not upgrades_scae_validity(packet, scae_ledger)

def persist_forecast_decision(packet, scae_ledger, ads_case_contract):
    write_forecast_decision(forecast_prob=scae_ledger.production_forecast_prob,
                            scae_artifact_ref=scae_ledger.artifact_id,
                            forecast_validity_status=scae_ledger.forecast_validity_status,
                            execution_authority_status=packet.execution_authority_status)

    if scae_ledger.forecast_validity_status == "invalid_for_forecast":
        return persist_status("forecast_not_scoreable_invalid_scae")

    baseline = ads_case_contract["prediction_time_market_baseline"]
    provenance = ads_case_contract["intake_source"]
    prediction_args = {
        "market_id": ads_case_contract["market_identity"]["internal_market_id"],
        "prediction_run_id": ads_case_contract["prediction_run_id"],
        "forecast_artifact_id": ads_case_contract["forecast_artifact_id"],
        "case_key": ads_case_contract["case_key"],
        "case_id": ads_case_contract["case_id"],
        "dispatch_id": ads_case_contract["dispatch_id"],
        "engine_stage": "scae",
        "prediction_source": "ads_pipeline",
        "prediction_label": "v2_scae",
        "predicted_probability": scae_ledger.production_forecast_prob,
        "predicted_at": scae_ledger.forecast_timestamp,
        "input_artifact_path": scae_ledger.input_manifest_path,
        "input_artifact_sha256": scae_ledger.input_manifest_sha256,
        "prediction_artifact_path": scae_ledger.artifact_path,
        "prediction_artifact_sha256": scae_ledger.artifact_sha256,
        "market_snapshot_id": baseline["market_snapshot_id"],
        "market_probability": baseline["market_probability"],
        "market_probability_method": baseline["market_probability_method"],
        "max_snapshot_age_seconds": baseline["max_snapshot_age_seconds"],
        "source_payload_hash": provenance["source_payload_hash"],
    }
    if baseline["snapshot_age_seconds"] <= baseline["max_snapshot_age_seconds"]:
        return record_market_prediction(**prediction_args)
    if ads_case_contract.get("fresh_snapshot_payload"):
        return record_prediction_with_snapshot(**prediction_args,
                                               snapshot_payload=ads_case_contract["fresh_snapshot_payload"])
    return write_pipeline_error_event("prediction_time_market_snapshot_stale", prediction_args)
```

Testing suite:

- Unit: synthesis-authored probability rejected.
- Unit: decision replacement probability rejected.
- Unit: decision can downgrade execution authority.
- Unit: decision cannot upgrade invalid SCAE forecast.
- Integration: persistence writes SCAE `production_forecast_prob` only.
- Integration: persistence creates or reuses exactly one idempotent `market_predictions` row per `prediction_run_id` / `forecast_artifact_id`.
- Integration: `market_predictions.market_snapshot_id`, `market_probability`, `market_probability_method`, `source_payload_hash`, artifact hashes, and case/dispatch IDs match the ADS case contract.
- Negative: stale or lookahead snapshot blocks scoreable persistence unless a fresh snapshot is atomically recorded with the prediction.

Completion checklist:

- [ ] Synthesis no-probability validation written.
- [ ] Decision no-replacement validation written.
- [ ] Forecast persistence source pinned to SCAE.
- [ ] Scoreable `market_predictions` bridge pinned to SCAE and ADS case contract snapshot provenance.
- [ ] `SYN-001`, `DEC-001`, `PERSIST-001`, and `PERSIST-002` inventory rows updated.

## Phase 10: Minimal Trace, Replay, Scoring, and Calibration-Debt Handoff

Goal: preserve non-authoritative learning and calibration material needed for replay and debt clearance, then hand maturity optimization to Session 6.

Implementation tasks:

- Write synchronous minimal trace pointer for every live run.
- Record decomposer and researcher resolved model IDs, model policy refs, prompt/template hashes, input/output artifact hashes, and schema versions in the trace.
- Enqueue first-100 direct-cutover replay manifests.
- Write replay result and outcome/scoring records when resolved outcomes become available.
- Use the existing resolution/scoring path to settle `market_predictions` rows and compute pipeline Brier, prediction-time market Brier, and Brier edge.
- Persist or reference scoring version, scoring timestamp, resolution source, resolution payload hash, market snapshot ID, prediction row ID, and scorecard artifact refs.
- Define calibration-debt clearance gates.
- Emit explicit handoff records for Session 6: trace IDs, replay cohort IDs, scorecard refs, active policy pointer refs, calibration-debt status, and protected component diagnostic requirements.
- Keep full trace materialization and optimization maturity separate from v2 live cutover and owned by Session 6.

Pseudocode:

```python
def write_minimal_trace(context, artifacts):
    model_calls = collect_model_execution_contexts(artifacts)
    for call in model_calls:
        assert call["resolved_model_id"] == "gpt-5.5-high" or call["model_lane_id"] == "amrg_model_assist"
        assert call["prompt_template_sha256"].startswith("sha256:")
    trace = {
        "trace_id": make_trace_id(context),
        "case_id": context.case_id,
        "dispatch_id": context.dispatch_id,
        "artifact_manifest_ids": [a.id for a in artifacts],
        "artifact_hashes": {a.id: a.sha256 for a in artifacts},
        "model_execution_contexts": model_calls,
        "live_forecast_authority": False,
    }
    persist("training_trace_runs", trace)

def calibration_debt_clearance_check(metrics, policy):
    return all([
        metrics.resolved_v2_cases >= policy.min_resolved_cases,
        metrics.tail_slice_cases >= policy.min_tail_slice_cases,
        metrics.max_ace <= policy.max_ace,
        metrics.max_log_loss_degradation <= policy.max_log_loss_degradation,
        metrics.catastrophic_tail_failures == 0,
        metrics.active_policy_pointer_stability_window_passed,
    ])

def score_resolved_prediction(prediction_row, resolved_market, score_policy):
    scored_row = settle_market_outcome(
        market_id=prediction_row.market_id,
        outcome=resolved_market.binary_outcome,
        resolution_source=resolved_market.resolution_source,
        resolution_payload_hash=resolved_market.resolution_payload_hash,
        scoring_version=score_policy.scoring_version,
    )
    scorecard = write_evaluator_scorecard({
        "prediction_id": scored_row.prediction_id,
        "market_id": scored_row.market_id,
        "market_snapshot_id": scored_row.market_snapshot_id,
        "prediction_run_id": scored_row.prediction_run_id,
        "forecast_artifact_id": scored_row.forecast_artifact_id,
        "prediction_brier": scored_row.prediction_brier,
        "market_brier": scored_row.market_brier,
        "brier_edge": scored_row.market_brier - scored_row.prediction_brier,
        "market_probability": scored_row.market_probability,
        "market_probability_method": scored_row.market_probability_method,
        "resolution_source": scored_row.resolution_source,
        "resolution_payload_hash": scored_row.resolution_payload_hash,
        "scoring_version": scored_row.scoring_version,
    })
    report = brier_score_report()
    return scorecard, report

def write_session6_handoff(trace_run, replay_result, scorecard, debt_status):
    handoff = {
        "handoff_type": "session6_evaluator_tuning_input",
        "trace_id": trace_run.trace_id,
        "replay_cohort_id": replay_result.cohort_id,
        "scorecard_ref": scorecard.artifact_ref,
        "calibration_debt_status": debt_status.status,
        "allowed_uses": ["full_trace_materialization", "candidate_policy_evaluation"],
        "forbidden_uses": ["production_forecast_write", "base_policy_rewrite"],
    }
    persist("evaluator_handoff_records", handoff)
```

Testing suite:

- Unit: minimal trace has no live authority.
- Unit: minimal trace records decomposer `gpt-5.5-high` model context.
- Unit: minimal trace records researcher `gpt-5.5-high` model context.
- Unit: trace rejects missing prompt template hash for decomposer or researcher model calls.
- Unit: first-100 completeness does not clear calibration debt alone.
- Unit: clearance requires resolved cases and tail gates.
- Unit: outcome scoring settles the linked `market_predictions` row and records pipeline Brier, market baseline Brier, Brier edge, scoring version, resolution source, and resolution payload hash.
- Unit: Brier report computes aggregate pipeline Brier, aggregate prediction-time market Brier, and average Brier edge from scoreable rows only.
- Unit: evaluator scorecard carries prediction row ID, market snapshot ID, `prediction_run_id`, `forecast_artifact_id`, and market baseline method for replay.
- Unit: calibration debt metrics read scored predictions and evaluator scorecards, not unscored decision records.
- Unit: Session 6 handoff forbids production forecast writes and base policy rewrites.

Completion checklist:

- [ ] Minimal trace pointer implemented or specified.
- [ ] Model provenance trace implemented or specified.
- [ ] Replay manifest/result records implemented or specified.
- [ ] Outcome/scoring bridge through existing `market_predictions` implemented or specified.
- [ ] Brier report and evaluator scorecard provenance implemented or specified.
- [ ] Calibration-debt clearance gates written.
- [ ] Session 6 handoff payload written.
- [ ] `TRACE-001`, `MODEL-004`, `REPLAY-001`, `SCORE-001`, and `CAL-001` inventory rows updated with correct stage labels.

## End-to-End Completion Checklist

- [ ] SCAE policy resolves from base policy and active profile context.
- [ ] Prior reliability and market-assimilation context are computed.
- [ ] Evidence delta candidates are bounded and quality-verified.
- [ ] Intra-leaf and cross-leaf duplicate/dependence guards work.
- [ ] Branch sub-ledgers work for expanded decompositions.
- [ ] Missingness/no-catalyst and family diagnostics are non-duplicative.
- [ ] Conditional AMRG recombination is accepted only for validated strict-precedence anchors.
- [ ] Research sufficiency context is present and blocks uncertified thin research.
- [ ] Final ledger emits all required probability fields.
- [ ] Calibration-debt controls affect production probability while active.
- [ ] Synthesis cannot author probability.
- [ ] Decision cannot replace probability.
- [ ] Forecast persistence writes only SCAE `production_forecast_prob`.
- [ ] Forecast persistence writes a scoreable `market_predictions` row with prediction-time market snapshot provenance.
- [ ] Resolution/scoring records pipeline Brier, prediction-time market Brier, and Brier edge with resolution provenance.
- [ ] Minimal training trace and replay records are non-authoritative.
- [ ] Maturity lanes are handed to Session 6 and do not block v2 live cutover.
- [ ] All Session 5 inventory rows have handoff artifacts and acceptance evidence.
