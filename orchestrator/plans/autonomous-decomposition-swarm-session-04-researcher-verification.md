# Session 04 Plan: Researcher Classification and Verification

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

- Section 1.1: no researcher-authored probabilities and quality verification before SCAE.
- Section 3.6: researcher swarm NLI classification.
- Section 8: researcher prompt contract.
- Section 9: researcher sidecar schema additions.
- Section 10: classification/provenance/verification persistence.
- Section 17.1: researcher prompt, sidecar, reconciliation migration surfaces.
- Section 18.1: live cutover classification and verification checklist.

## Mission

Replace probability-authoring researcher output with NLI evidence classification and machine-owned verification. Researchers classify evidence against QDT leaves and the macro question. Verification gates directionality and evidence quality before SCAE can consume rows.

This session must not let researcher prompts, sidecars, or reconciliation artifacts contain `own_probability`, final macro probability, fair value, interval, linear pooling, or reassembled probability fields in v2 mode.

## Runtime Script Placement

Session 4 belongs to ADS Researcher Swarm. Place researcher orchestration, leaf researcher spawning, no-probability sidecar validation, coverage proof, verification, and sufficiency reconciliation scripts under `/Users/agent2/.openclaw/researcher-swarm/scripts`. Add any new path to `plans/autonomous-decomposition-swarm-script-placement-map.md` before implementation.

Planned Session 4 paths:

```text
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/run_researcher_swarm.py
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/build_leaf_research_assignments.py
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/validate_researcher_context_isolation.py
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/evaluate_researcher_escalations.py
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/spawn_leaf_researchers.py
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/validate_researcher_sidecars.py
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/verify_evidence_directionality.py
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/verify_evidence_quality.py
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/validate_scae_readiness.py
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/reconcile_research_sufficiency.py
/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/assignments.py
/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/isolation.py
/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/escalation.py
/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/classification.py
/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/verification.py
/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/subagents.py
```

Ownership boundaries:

- ADS Researcher Swarm may spawn bounded leaf researcher subagents from a validated QDT and retrieval packet.
- It must not generate or repair the QDT, write SCAE ledger records, or persist any probability field.
- Orchestrator receives only schema-valid, artifact-manifested research and verification outputs before kicking SCAE.

## Owned Inventory Rows

Directly owned rows:

- `CLS-001`: NLI classification prompt contract.
- `CLS-006`: compact `leaf-research-assignment/v1` subagent packet contract.
- `CLS-008`: researcher subagent context isolation contract.
- `CLS-002`: no-probability sidecar schema.
- `CLS-003`: evidence classification matrix.
- `CLS-004`: supplemental evidence normalization boundary.
- `CLS-005`: researcher evidence-review coverage proof.
- `CLS-007`: adaptive researcher escalation decision contract.
- `MODEL-003`: resolve and record `gpt-5.5-high` researcher leaf NLI model lane.
- `VER-001`: direction verification slices.
- `VER-002`: evidence-quality verification slices.
- `VER-003`: SCAE-readiness validation.
- `VER-004`: high-certainty research sufficiency reconciliation.

## Coordination Rules

1. Update only Session 4 rows directly.
2. Do not mark `CLS-001` integration-ready until `QDT-002`, `QDT-005`, `RET-001`, and `RET-008` exist.
3. Do not mark `CLS-006` integration-ready until `CLS-001`, `QDT-005`, `RET-008`, `MODEL-003`, and `FND-003` exist.
4. Do not mark `CLS-008` integration-ready until `CLS-006`, `MODEL-003`, `FND-003`, and `FND-006` exist.
5. Do not spawn any leaf researcher until its isolated context packet passes allowlist/denylist validation and writes a context-isolation audit.
6. Do not mark `CLS-003` integration-ready until `RET-004` exists.
7. Do not mark `CLS-005` integration-ready until `CLS-006`, `CLS-008`, and `RET-008` exist.
8. Do not mark `CLS-007` integration-ready until `CLS-003`, `CLS-005`, `VER-001`, `VER-002`, `RET-008`, `QDT-005`, and `POL-003` exist.
9. Do not mark `VER-*` integration-ready until `FND-004` exists.
10. Do not mark `VER-004` integration-ready until `CLS-005`, `CLS-007`, `RET-008`, `VER-001`, `VER-002`, and `VER-003` exist.
11. Do not spawn extra researcher assignments unless `researcher-escalation-decision/v1` records at least one configured trigger and an explicit bounded assignment count.
12. The default is one primary researcher per leaf; extra researchers are confirmation/escalation attempts, not alternate probability authors.
13. Escalation logic must not write probabilities, fair values, intervals, SCAE deltas, or decision recommendations. High-leverage triggers use only a pre-SCAE leverage proxy.
14. If retrieval provenance or sufficiency certificate fields are missing fields needed for verification, propose changes against Session 3 rows rather than silently inventing fields.
15. If SCAE needs additional verification output fields, coordinate with Session 5 through proposed inventory changes.
16. A researcher-swarm launch is successful only when at least one isolated `leaf-research-assignment/v1` packet is delivered to, or already active for, a leaf researcher. Bare `accepted`, `started`, or timeout states with zero delivered/active isolated assignments must not advance the case.

## Migration and Write Path Ownership

Session 4 owns `MIG-006` assignment/classification/verification records. Runtime integration is blocked until these write paths have destination tables, schemas, or explicit artifact contracts in the shared migration matrix.

Required write paths:

```text
write_researcher_prompt_artifact
write_leaf_research_assignments
write_researcher_context_isolation_audits
write_researcher_classifications
write_classification_provenance_slices
write_researcher_coverage_proofs
write_researcher_escalation_decisions
write_normalized_supplemental_evidence
write_direction_verification_slices
write_evidence_quality_verification_slices
write_scae_readiness_reconciliation
write_research_sufficiency_reconciliation
```

The assignment write path must store only compact per-leaf subagent packets and hashes: no full evidence documents, no duplicated QDT leaf blobs, and no narrative research instructions beyond short bounded `reason_codes` or validator-required excerpts. The isolation write path must store allowlist/denylist digests, visible artifact refs, forbidden-ref scan results, fresh-context launch status, and peer-output exclusion proof. The classification write path must store leaf classifications, extracted values, quality dimensions, condition scope, provenance refs, researcher coverage proofs, assignment refs, and researcher model provenance. The escalation write path must store trigger codes, trigger refs, caps, additional assignment counts, assignment refs, completion status, and decision digests without duplicating evidence bodies or researcher transcripts. The verification write paths must store side-mapping checks, quality multiplier inputs, accepted/excluded status, deadlock-safe exclusions, SCAE-readiness, and high-certainty research sufficiency reconciliation. These records are the future tuning basis for researcher prompt quality, model choice, evidence-quality weighting, escalation value, context-contamination rates, side-mapping errors, verifier deadlock handling, and whether sufficiency requirements predicted better resolved calibration.

## Technical Specification

### Leaf Research Assignment Artifact

`leaf-research-assignment/v1` is the compact per-leaf packet that ADS Researcher Swarm sends to a leaf researcher subagent. It is a machine-readable routing and obligation contract, not a research report.

Storage rules:

- Store one assignment per leaf and researcher attempt.
- Store refs and hashes, not duplicated payloads.
- Evidence bodies stay in retrieval artifacts; assignments carry `evidence_refs`, optional byte/char offsets, and snippet hashes.
- QDT leaf details stay in the QDT artifact; assignments carry `leaf_ref`, stable IDs, compact enums, and requirement IDs.
- Prompt text stays in prompt artifacts; assignments carry `prompt_template_id` and `prompt_template_sha256`.
- Do not include probabilities, fair values, intervals, decision recommendations, or SCAE ledger refs.

Minimum artifact:

```json
{
  "schema_version": "leaf-research-assignment/v1",
  "assignment_id": "leaf-assignment-...",
  "attempt_index": 0,
  "assignment_role": "primary|escalation|confirmation",
  "escalation_decision_ref": null,
  "trigger_codes": [],
  "assigned_lens": "baseline|source_of_truth_check|conflict_resolution|skeptical_countercheck|unanswerability_confirmation",
  "context_isolation": {
    "isolation_policy_id": "researcher-context-isolation/v1",
    "isolation_audit_ref": "researcher-context-isolation-...",
    "peer_context_allowed": false,
    "visible_artifact_ref_allowlist": [],
    "forbidden_artifact_ref_patterns": [
      "researcher-sidecar:*",
      "researcher-escalation-decision:*:peer",
      "scae-ledger:*",
      "market-prediction:*",
      "replay-result:*",
      "outcome-scoring:*"
    ]
  },
  "case_id": "case-...",
  "dispatch_id": "dispatch-...",
  "leaf_id": "leaf-...",
  "parent_branch_id": "branch-...",
  "leaf_ref": {
    "artifact_ref": "artifact:question-decomposition/...",
    "leaf_json_pointer": "/required_leaf_questions/0",
    "leaf_digest": "sha256:..."
  },
  "condition_scope": "unconditional|conditional|branch_local",
  "sufficiency_requirement_refs": [],
  "research_sufficiency_certificate_ref": "research-sufficiency-...",
  "retrieval_breadth_profile_ref": "breadth-profile-...",
  "retrieval_breadth_coverage_ref": "breadth-coverage-...",
  "assigned_evidence_refs": [
    {
      "evidence_ref": "retrieval-evidence-...",
      "claim_family_id": "claim-family-...",
      "source_family_id": "source-family-...",
      "source_class": "official_or_primary|primary_reporting|independent_secondary|market_rules_or_resolution_source|market_price_or_orderbook|social_or_user_generated|unknown",
      "snippet_ref": "artifact:retrieval-snippet/...",
      "snippet_sha256": "sha256:..."
    }
  ],
  "required_value_field_ids": [],
  "required_negative_check_ids": [],
  "output_contract": {
    "sidecar_schema_version": "researcher-sidecar/v2",
    "classification_schema_version": "researcher-classification/v1",
    "coverage_proof_required": true,
    "forbidden_fields": ["own_probability", "fair_value", "interval", "macro_probability", "decision_recommendation"]
  },
  "model_execution_context": {
    "model_lane_id": "researcher_leaf_nli_classification",
    "resolved_model_id": "gpt-5.5-high",
    "model_policy_ref": "plans/autonomous-decomposition-swarm-model-lane-policy.json",
    "prompt_template_id": "researcher-leaf-nli/v1",
    "prompt_template_sha256": "sha256:..."
  },
  "budget": {
    "max_input_tokens": 12000,
    "max_output_tokens": 2500,
    "deadline_seconds": 900,
    "retry_budget": 1
  },
  "artifact_outputs": {
    "sidecar_artifact_ref": "artifact:researcher-sidecar/...",
    "coverage_proof_ref": "coverage-proof-..."
  },
  "assignment_digest": "sha256:..."
}
```

### Researcher Context Isolation Audit

`researcher-context-isolation/v1` proves that a leaf researcher was launched with a siloed context. It is checked before `spawn_leaf_researchers.py` sends a packet and is persisted through `write_researcher_context_isolation_audits()`.

Isolation rules:

- Each researcher subagent gets a fresh context per assignment.
- The subagent receives only its own `leaf-research-assignment/v1`, allowed evidence/snippet refs, sidecar schema refs, prompt template refs, and model lane context.
- The subagent receives breadth profile and breadth coverage refs for its assigned leaf only; it may verify/review those obligations but must not broaden retrieval on its own.
- Leaf researchers do not perform broad internet search. If assigned evidence is insufficient, contradictory, stale, or missing a required breadth dimension, the sidecar records a structured gap so Researcher Swarm can route a bounded retrieval expansion/escalation through Session 3-owned retrieval contracts.
- The subagent must not receive sibling leaf assignments, peer sidecars, previous researcher outputs for the same leaf, escalation decisions for other researchers, aggregate research summaries, SCAE ledger refs, forecast/decision refs, replay/scoring surfaces, or resolved outcomes.
- Context reuse between leaf researchers is forbidden unless the reused content is a shared immutable schema/prompt template ref.
- Cross-researcher comparison, conflict reconciliation, and aggregation happen only in verifier/reconciliation code after individual sidecars are sealed.

Minimum audit:

```json
{
  "schema_version": "researcher-context-isolation/v1",
  "isolation_audit_id": "researcher-context-isolation-...",
  "case_id": "case-...",
  "dispatch_id": "dispatch-...",
  "assignment_id": "leaf-assignment-...",
  "leaf_id": "leaf-...",
  "subagent_session_ref": "agent:researcher-swarm:subagent:...",
  "fresh_context": true,
  "visible_artifact_refs": [
    "artifact:leaf-research-assignment/...",
    "artifact:retrieval-snippet/...",
    "artifact:researcher-sidecar-schema/..."
  ],
  "visible_artifact_refs_digest": "sha256:...",
  "forbidden_ref_scan": {
    "peer_assignment_refs_present": false,
    "peer_sidecar_refs_present": false,
    "aggregate_summary_refs_present": false,
    "scae_refs_present": false,
    "prediction_scoring_refs_present": false,
    "outcome_refs_present": false
  },
  "allowed_shared_refs": [
    "prompt-template:researcher-leaf-nli/v1",
    "schema:researcher-sidecar/v2"
  ],
  "launch_allowed": true,
  "reason_codes": [],
  "audit_digest": "sha256:..."
}
```

### Researcher Prompt Contract

Prompt inputs:

```text
macro question
read-only market reality constraints
family-aware contract context when applicable
evidence packet summary
leaf-research-assignment/v1 packet
QDT leaf refs, not full QDT artifact bodies
per-leaf research sufficiency requirements
retrieval breadth profile and breadth coverage refs for the assigned leaf
retrieval packet selected evidence refs
retrieval sufficiency certificate refs and expansion summaries
sidecar schema contract
assigned artifact paths
model lane execution context
researcher-context-isolation/v1 audit ref
```

Forbidden prompt asks:

```text
leaf_probability
researcher_reassembled_probability
own_probability
fair_value_low
fair_value_mid
fair_value_high
probability interval
final macro probability
decision recommendation
sibling leaf assignment
peer researcher output
aggregate research summary
SCAE ledger or forecast output
replay, outcome, or scoring artifact
```

### Sidecar Classification Object

Minimum classification object:

```json
{
  "classification_id": "classification-...",
  "model_execution_context": {
    "model_lane_id": "researcher_leaf_nli_classification",
    "resolved_model_id": "gpt-5.5-high",
    "model_policy_ref": "plans/autonomous-decomposition-swarm-model-lane-policy.json",
    "prompt_template_id": "researcher-leaf-nli/v1",
    "prompt_template_sha256": "sha256:...",
    "sidecar_schema_version": "researcher-sidecar/v2",
    "classification_output_schema_version": "researcher-classification/v1"
  },
  "leaf_id": "leaf-...",
  "parent_branch_id": "branch-...",
  "leaf_condition_scope": "unconditional",
  "evidence_ref": "retrieval-evidence-...",
  "research_sufficiency_certificate_ref": "research-sufficiency-...",
  "coverage_proof_ref": "coverage-proof-...",
  "impact_direction": "supports_yes|supports_no|neutral",
  "evidence_strength": "definitive|strong|moderate|weak|none|unanswerable",
  "classification_confidence": "high|medium|low",
  "answer_value_extraction": {
    "field_name": "...",
    "value": "...",
    "normalization_status": "parsed|not_applicable|failed"
  },
  "evidence_quality_dimensions": {
    "source_authority": "high|medium|low|unknown",
    "directness": "direct|indirect|background|unknown",
    "recency": "fresh|stale|timeless|unknown",
    "specificity": "specific|general|ambiguous|unknown"
  },
  "provenance_refs": [],
  "unmodeled_material_dimension_flags": []
}
```

### Researcher Coverage Proof Object

Each sidecar must include a compact proof that the researcher reviewed the certified inputs required for the leaf. This is not narrative; it is an auditable coverage join between QDT requirements, retrieval evidence, and classifications:

```json
{
  "coverage_proof_id": "coverage-proof-...",
  "leaf_id": "leaf-...",
  "research_sufficiency_certificate_ref": "research-sufficiency-...",
  "retrieval_breadth_coverage_ref": "breadth-coverage-...",
  "evidence_refs_assigned": [],
  "evidence_refs_reviewed": [],
  "source_class_ids_reviewed": [],
  "claim_family_ids_reviewed": [],
  "source_family_ids_reviewed": [],
  "requirements_reviewed": [],
  "requirements_answered": [],
  "requirements_unanswered": [],
  "required_value_fields_extracted": [],
  "required_negative_checks_completed": [],
  "source_gap_flags": [],
  "structural_unanswerability_acknowledged": false,
  "machine_readability_status": "schema_valid|schema_invalid"
}
```

### Adaptive Researcher Escalation Decision

`researcher-escalation-decision/v1` determines whether a leaf needs additional researcher assignments beyond the default primary assignment. It is a bounded routing artifact, not a forecast, and it must not contain probability fields.

Default policy:

- Start with one primary researcher assignment per leaf.
- Use a maximum of five concurrent leaf researcher subagents per case; queue excess assignments.
- Add one additional assignment per triggered leaf by default.
- Cap each leaf at three total assignments unless an explicit policy waiver is recorded.
- Structural unanswerability and critical/source-of-truth leaves can require two independent confirmations before `VER-004` may mark the leaf SCAE-ready or structurally unanswerable.

Escalation trigger codes:

```text
critical_source_of_truth_leaf
evidence_conflict
low_retrieval_confidence
low_classification_confidence
high_scae_leverage_proxy
structural_unanswerability_claimed
```

The high-leverage trigger uses a pre-SCAE leverage proxy only. It may combine QDT static information weight, leaf criticality, condition scope, dependency group, verified evidence strength/quality, retrieval confidence, and SCAE policy cap context. It must not compute or store probability, odds, fair value, interval, SCAE delta, or decision recommendation.

Minimum decision object:

```json
{
  "schema_version": "researcher-escalation-decision/v1",
  "decision_id": "researcher-escalation-...",
  "case_id": "case-...",
  "dispatch_id": "dispatch-...",
  "leaf_id": "leaf-...",
  "base_assignment_id": "leaf-assignment-...",
  "trigger_codes": [
    "evidence_conflict"
  ],
  "trigger_evidence_refs": [],
  "retrieval_quality_ref": "retrieval-quality-...",
  "classification_ids": [],
  "verification_slice_refs": [],
  "pre_scae_leverage_proxy": {
    "bucket": "low|medium|high",
    "input_refs": [],
    "reason_codes": [],
    "probability_fields_forbidden": true
  },
  "escalation_required": true,
  "additional_assignment_count": 1,
  "max_assignments_for_leaf": 3,
  "max_concurrent_leaf_researchers_per_case": 5,
  "escalation_assignment_refs": [],
  "completion_status": "not_required|required_pending|required_complete|cap_reached|blocked",
  "decision_digest": "sha256:..."
}
```

Escalation output rules:

- Extra assignments reuse `leaf-research-assignment/v1` with `assignment_role="escalation"` or `assignment_role="confirmation"`.
- Extra assignments use compact refs and hashes only; they do not duplicate evidence bodies, QDT leaf blobs, or prior sidecar text.
- Escalation is complete only when required extra assignment refs are delivered/already active and their sidecars pass no-probability validation, coverage proof validation, and direction/quality verification.
- If required escalation cannot be delivered, `VER-004` must not mark the leaf as cleanly SCAE-ready.

### Verification Outputs

Direction verification:

```json
{
  "verification_slice_id": "direction-...",
  "classification_id": "classification-...",
  "claimed_direction": "supports_yes",
  "verified_direction": "supports_yes|supports_no|neutral|ambiguous|excluded",
  "side_mapping_digest": "sha256:...",
  "market_constraints_digest": "sha256:...",
  "method_status": "verified|ambiguous|quarantined|excluded",
  "reason_codes": []
}
```

Quality verification:

```json
{
  "quality_verification_slice_id": "quality-...",
  "classification_id": "classification-...",
  "claimed_quality_fields": {},
  "machine_normalized_quality_fields": {},
  "accepted_quality_fields": {},
  "raw_quality_multiplier": 1.0,
  "quality_correlation_groups": [],
  "correlated_quality_floor_applied": false,
  "final_quality_multiplier": 1.0,
  "reason_codes": []
}
```

Research sufficiency reconciliation:

```json
{
  "research_sufficiency_reconciliation_id": "sufficiency-reconcile-...",
  "dispatch_id": "dispatch-...",
  "leaf_id": "leaf-...",
  "certificate_ref": "research-sufficiency-...",
  "coverage_proof_ref": "coverage-proof-...",
  "reconciled_status": "scae_ready_high_certainty|structurally_unanswerable|blocked_insufficient_research|excluded",
  "missing_requirement_codes": [],
  "scae_ready": true
}
```

## Phase 0: Anchor and Dependency Gate

Goal: confirm Session 4 ownership and upstream status.

Pseudocode:

```python
owned = ["CLS-001", "CLS-006", "CLS-008", "CLS-002", "CLS-003", "CLS-004", "CLS-005", "CLS-007", "MODEL-003",
         "VER-001", "VER-002", "VER-003", "VER-004"]
for feature_id in owned:
    assert inventory.owner(feature_id) == "Session 4"

if mode == "runtime_integration":
    assert_done("QDT-002")
    assert_done("QDT-005")
    assert_done("RET-001")
    assert_done("RET-008")
    assert_done("RET-004")
    assert_done("FND-004")
    assert_done("MODEL-001")
    assert_done("CLS-006")
    assert_done("CLS-008")
    assert_done("CLS-007")
```

Tests:

- Static: all owned rows exist.
- Gate: integration blocks without QDT and retrieval packet contracts.
- Gate: fixture sidecars can be tested against local fixture schemas.

Checklist:

- [ ] Active rows marked `in_progress`.
- [ ] Upstream blockers recorded.
- [ ] Fixture or integration mode declared.

## Phase 1: Leaf Assignment and NLI Researcher Prompt Contract

Goal: make researcher tasks evidence classification, not forecasting.

Implementation tasks:

- Build compact `leaf-research-assignment/v1` packets for every dispatchable QDT leaf.
- Store only refs, digests, compact enums, required field IDs, negative-check IDs, model lane context, prompt hash, and output artifact refs.
- Render macro question and read-only market reality constraints.
- Render flattened required leaves.
- Render per-leaf research sufficiency requirements.
- Render retrieval breadth profile and coverage refs for the assigned leaf.
- Render evidence by leaf.
- Render retrieval sufficiency certificate refs and expansion summary by leaf.
- Render condition scope explicitly.
- Render no-probability rule.
- Render output sidecar contract.
- Resolve `researcher_leaf_nli_classification` from `plans/autonomous-decomposition-swarm-model-lane-policy.json`.
- Build and validate `researcher-context-isolation/v1` before each subagent launch.
- Launch each leaf researcher in a fresh context scoped to its own assignment and immutable shared schema/prompt refs.
- Preserve optional classification lenses only as assignment metadata for baseline/escalation/confirmation work, not as probability priors or a requirement to run five personas on every leaf.

Pseudocode:

```python
def build_leaf_research_assignment(
    leaf,
    retrieval_packet,
    model_context,
    *,
    assignment_role="primary",
    attempt_index=0,
    escalation_decision=None,
):
    cert = retrieval_packet.sufficiency_certificate_for(leaf.leaf_id)
    breadth_profile = retrieval_packet.breadth_profile_for(leaf.leaf_id)
    breadth_coverage = retrieval_packet.breadth_coverage_for(leaf.leaf_id)
    evidence_refs = retrieval_packet.evidence_refs_for(leaf.leaf_id)
    return {
        "schema_version": "leaf-research-assignment/v1",
        "assignment_id": stable_id("leaf-assignment", leaf.leaf_id, cert.id, attempt_index, assignment_role),
        "attempt_index": attempt_index,
        "assignment_role": assignment_role,
        "escalation_decision_ref": escalation_decision.ref if escalation_decision else None,
        "trigger_codes": escalation_decision.trigger_codes if escalation_decision else [],
        "assigned_lens": assigned_lens_for(assignment_role, escalation_decision),
        "leaf_id": leaf.leaf_id,
        "parent_branch_id": leaf.parent_branch_id,
        "leaf_ref": leaf.compact_ref(),
        "condition_scope": leaf.leaf_condition_scope,
        "sufficiency_requirement_refs": leaf.sufficiency_requirement_refs,
        "research_sufficiency_certificate_ref": cert.ref,
        "retrieval_breadth_profile_ref": breadth_profile.ref,
        "retrieval_breadth_coverage_ref": breadth_coverage.ref,
        "assigned_evidence_refs": compact_evidence_refs(evidence_refs),
        "required_value_field_ids": leaf.required_value_field_ids,
        "required_negative_check_ids": leaf.required_negative_check_ids,
        "output_contract": no_probability_output_contract(),
        "model_execution_context": model_context,
        "budget": leaf_research_budget(leaf.criticality),
        "artifact_outputs": planned_outputs_for(leaf.leaf_id),
    }

def validate_researcher_context_isolation(assignment):
    visible_refs = collect_visible_refs(assignment)
    forbidden = scan_for_forbidden_refs(
        visible_refs,
        patterns=[
            "peer_leaf_assignment",
            "peer_researcher_sidecar",
            "aggregate_research_summary",
            "scae_ledger",
            "market_prediction",
            "replay_result",
            "outcome_scoring",
        ],
    )
    return {
        "schema_version": "researcher-context-isolation/v1",
        "assignment_id": assignment["assignment_id"],
        "leaf_id": assignment["leaf_id"],
        "fresh_context": true,
        "visible_artifact_refs_digest": digest_refs(visible_refs),
        "forbidden_ref_scan": forbidden,
        "launch_allowed": not any(forbidden.values()),
    }

def build_researcher_prompt(persona, assignment, evidence_packet):
    prompt = Prompt()
    prompt.add_macro_question(evidence_packet.macro_question)
    prompt.add_market_constraints(evidence_packet.market_reality_constraints)
    prompt.add_family_context(evidence_packet.family_context)
    prompt.add_assignment(assignment)
    prompt.add_evidence_refs(assignment["assigned_evidence_refs"])
    prompt.add_retrieval_breadth_refs(
        assignment["retrieval_breadth_profile_ref"],
        assignment["retrieval_breadth_coverage_ref"],
    )
    prompt.add_research_sufficiency_certificate(assignment["research_sufficiency_certificate_ref"])
    prompt.add_context_isolation_ref(assignment["context_isolation"]["isolation_audit_ref"])
    if assignment["condition_scope"] != "unconditional":
        prompt.add_condition_scope_instruction(assignment["condition_scope"])
    prompt.add_forbidden_fields(["own_probability", "fair_value", "interval", "macro_probability"])
    prompt.add_forbidden_context_refs(["peer_sidecar", "sibling_assignment", "scae_ledger", "replay_result", "outcome_scoring"])
    prompt.add_model_execution_context(assignment["model_execution_context"])
    prompt.add_sidecar_schema_ref("researcher-sidecar-v2")
    return prompt

def resolve_model_lane(lane_id):
    policy = read_json("plans/autonomous-decomposition-swarm-model-lane-policy.json")
    lane = policy["lanes"][lane_id]
    assert lane["default_model_id"] == "gpt-5.5-high"
    return {
        "model_lane_id": lane_id,
        "resolved_model_id": lane["default_model_id"],
        "model_policy_ref": policy["policy_id"],
        "prompt_template_id": "researcher-leaf-nli/v1",
    }
```

Testing suite:

- Unit: assignment schema rejects embedded evidence body text above a tiny configured excerpt cap.
- Unit: assignment schema rejects duplicated full QDT leaf objects when `leaf_ref` is available.
- Unit: assignment has stable IDs, artifact refs, prompt hash, model lane context, budget/deadline caps, output refs, and assignment digest.
- Unit: assignment includes a context-isolation policy ref and isolation audit ref.
- Unit: assignment includes retrieval breadth profile and coverage refs for the assigned leaf.
- Unit: context-isolation validation rejects sibling assignment refs, peer sidecars, aggregate research summaries, SCAE refs, replay/scoring refs, and outcome refs.
- Unit: leaf researcher spawn is blocked when `launch_allowed=false`.
- Unit: two researchers on the same leaf get independent fresh-context audits and neither sees the other's sidecar.
- Unit: assignment rejects probability/fair-value/interval/decision fields anywhere recursively.
- Snapshot: prompt contains macro question, constraints, leaves, and evidence refs.
- Snapshot: prompt contains sufficiency requirements and certificate refs for each leaf.
- Snapshot: prompt contains breadth profile and coverage refs for the assigned leaf.
- Unit: condition-scoped leaves include explicit condition text.
- Unit: prompt excludes probability/fair-value/interval asks.
- Unit: prompt resolves `researcher_leaf_nli_classification` to `gpt-5.5-high`.
- Unit: prompt requires prompt template hash and sidecar schema version in output metadata.
- Unit: prompt rendering fails if retrieval packet classification dispatch status is not `allowed`.
- Unit: persona prompt cannot override no-probability contract.
- Unit: primary assignment has `assignment_role="primary"` and no escalation trigger codes.
- Unit: escalation assignment has `assignment_role="escalation"` or `assignment_role="confirmation"` and links to `researcher-escalation-decision/v1`.
- Regression: legacy probability text is rejected in v2 mode.

Completion checklist:

- [ ] `leaf-research-assignment/v1` schema written.
- [ ] Assignment builder written.
- [ ] Assignment storage/ref compaction checks written.
- [x] Context-isolation audit schema and validator written.
- [ ] Escalation assignment fields written.
- [ ] Prompt contract written.
- [ ] Researcher model lane resolution written.
- [ ] Forbidden field list written.
- [ ] Condition-scope rendering written.
- [ ] Sufficiency requirement and certificate rendering written.
- [ ] `CLS-001`, `CLS-006`, `CLS-007`, and `MODEL-003` inventory rows updated.

## Phase 2: No-Probability Sidecar Schema

Goal: make v2 researcher artifacts schema-valid only when they contain classifications and no probabilities.

Implementation tasks:

- Define sidecar v2 schema.
- Reject legacy probability fields in v2 mode.
- Require classification coverage by leaf or validated unanswerable classification.
- Require retrieval evidence refs or supplemental evidence refs.
- Require coverage proof for every classified leaf.
- Require `research_sufficiency_certificate_ref` on every classification.
- Require market constraints digest and classification matrix digest.

Pseudocode:

```python
FORBIDDEN_V2_FIELDS = [
    "own_probability",
    "leaf_probability",
    "researcher_reassembled_probability",
    "final_macro_probability",
    "fair_value_low",
    "fair_value_mid",
    "fair_value_high",
    "probability_interval",
]

def validate_sidecar_v2(sidecar, qdt):
    for field in FORBIDDEN_V2_FIELDS:
        if field in recursive_keys(sidecar):
            return invalid("forbidden_probability_field", field)
    required_leaf_ids = {leaf.leaf_id for leaf in qdt.required_leaf_questions}
    covered_leaf_ids = {c.leaf_id for c in sidecar.required_question_classifications}
    if not required_leaf_ids <= covered_leaf_ids:
        return invalid("classification_coverage_missing")
    for classification in sidecar.required_question_classifications:
        if not classification.research_sufficiency_certificate_ref:
            return invalid("research_sufficiency_certificate_ref_missing", classification.leaf_id)
        if not sidecar.coverage_proof_for(classification.leaf_id):
            return invalid("coverage_proof_missing", classification.leaf_id)
    return valid()
```

Testing suite:

- Unit: sidecar with `own_probability` rejected.
- Unit: sidecar missing required leaf rejected.
- Unit: sidecar missing coverage proof rejected.
- Unit: sidecar missing sufficiency certificate ref rejected.
- Unit: unanswerable classification requires provenance and rationale.
- Unit: invalid impact direction rejected.
- Unit: sidecar with valid classifications passes.
- Unit: sidecar missing model execution context is rejected.

Completion checklist:

- [ ] Sidecar schema written.
- [ ] Forbidden v2 fields enforced.
- [ ] Coverage validator written.
- [ ] Coverage proof validator written.
- [ ] Sufficiency certificate refs required.
- [ ] `CLS-002` inventory row updated.

## Phase 3: Classification Matrix Materialization

Goal: transform valid sidecars into first-class classification and provenance records.

Implementation tasks:

- Materialize `persona_evidence_classification_slices`.
- Materialize `persona_evidence_provenance_slices`.
- Preserve leaf, branch, condition scope, evidence ref, source/claim-family refs, and quality dimensions.
- Preserve sufficiency certificate ref and coverage proof ref.
- Keep one ledger-ready row per claim/source/question/condition scope.
- Split or reject composite multi-claim classifications.

Pseudocode:

```python
def materialize_classification_matrix(sidecars, qdt, retrieval_packet):
    rows = []
    for sidecar in sidecars:
        validate_sidecar_v2(sidecar, qdt)
        for classification in sidecar.required_question_classifications:
            evidence = retrieval_packet.lookup(classification.evidence_ref)
            if is_composite_multi_claim(classification, evidence):
                split_rows = split_or_reject_composite(classification, evidence)
                rows.extend(split_rows)
            else:
                rows.append(make_classification_slice(sidecar.persona, classification, evidence))
    return rows

def materialize_coverage_proofs(sidecars, retrieval_packet):
    proofs = []
    for sidecar in sidecars:
        for proof in sidecar.coverage_proofs:
            certificate = retrieval_packet.lookup_certificate(proof.research_sufficiency_certificate_ref)
            if not set(proof.evidence_refs_reviewed) <= set(proof.evidence_refs_assigned):
                raise ValidationError("reviewed_unassigned_evidence")
            if missing_required_review(proof, certificate):
                raise ValidationError("research_requirement_not_reviewed")
            proofs.append(make_coverage_proof_slice(proof, certificate))
    return proofs
```

Testing suite:

- Unit: valid sidecar yields classification slices.
- Unit: provenance refs are required and resolvable.
- Unit: composite multi-claim evidence is split or rejected.
- Unit: condition-scoped classification retains condition scope.
- Unit: coverage proof cannot claim unassigned evidence.
- Unit: coverage proof must address certificate requirements.
- Integration: fixture sidecars produce complete matrix digest.

Completion checklist:

- [ ] Classification slice schema mapped.
- [ ] Provenance slice schema mapped.
- [ ] Composite claim handling defined.
- [ ] Matrix digest generated.
- [ ] Coverage proof slices generated.
- [ ] `CLS-003` inventory row updated.
- [ ] `CLS-005` inventory row updated.

## Phase 4: Supplemental Evidence Normalization

Goal: ensure researcher-discovered supplemental evidence passes a machine-owned canonicalization boundary before SCAE.

Implementation tasks:

- Accept raw supplemental citation refs from sidecars.
- Fetch or verify source when policy permits.
- Assign canonical source ID, event-source family, claim-family ID, content hash, temporal gate, source class, source-family, and independence fields.
- Support bounded degraded path for non-critical transient fetch failures.
- Support protected-primary access blocked path separately.

Pseudocode:

```python
def normalize_supplemental_evidence(raw_ref, dispatch):
    fetched = fetch_source(raw_ref)
    if not fetched.ok:
        if raw_ref.is_protected_primary:
            return protected_primary_access_blocked(raw_ref)
        if can_use_degraded_path(raw_ref):
            return degraded_supplemental_record(raw_ref, caps=policy.degraded_caps)
        return reject("supplemental_fetch_failed")
    temporal = validate_temporal_eligibility(fetched, dispatch)
    if not temporal.ok:
        return reject("temporal_isolation_failed")
    return normalized_supplemental_evidence(
        canonical_source_id=canonical_source(fetched),
        claim_family_id=deterministic_claim_family(fetched.claim),
        content_sha256=sha256(fetched.content),
        temporal_gate_metadata=temporal.metadata,
    )
```

Testing suite:

- Unit: supplemental source after forecast timestamp rejected.
- Unit: protected primary access failure produces dedicated status.
- Unit: degraded non-critical path has capped source class and blockers.
- Unit: critical/source-of-truth supplemental evidence cannot use degraded path.
- Integration: normalized supplemental evidence can join classification matrix.

Completion checklist:

- [ ] Supplemental normalization contract written.
- [ ] Degraded path rules written.
- [ ] Protected-primary path written.
- [ ] `CLS-004` inventory row updated.

## Phase 5: Direction Verification

Goal: independently verify non-neutral classification direction against side mapping and market constraints before SCAE.

Implementation tasks:

- Load market side mapping and constraints digest.
- Verify `supports_yes` / `supports_no` semantics.
- Mark ambiguous rows as quarantined or excluded according to policy.
- Preserve coverage-after-exclusion status.
- Avoid operational deadlock when non-critical ambiguous rows can be safely excluded.

Pseudocode:

```python
def verify_direction(classification, evidence_packet):
    if classification.impact_direction == "neutral":
        return direction_slice(classification, verified_direction="neutral", method_status="verified")
    mapped = apply_side_mapping(classification, evidence_packet.market_reality_constraints.side_mapping)
    if mapped.conflicts_with_constraints:
        return direction_slice(classification, verified_direction="excluded", method_status="excluded",
                               reason_codes=["side_mapping_conflict"])
    if mapped.ambiguous:
        return direction_slice(classification, verified_direction="ambiguous", method_status="quarantined",
                               reason_codes=["direction_ambiguous"])
    return direction_slice(classification, verified_direction=mapped.direction, method_status="verified")
```

Testing suite:

- Unit: neutral classification passes without sign.
- Unit: side-map contradiction excluded.
- Unit: ambiguous direction quarantined.
- Unit: coverage-after-exclusion recorded.
- Integration: all non-neutral fixture rows receive direction verification.

Completion checklist:

- [ ] Direction verification slice schema written.
- [ ] Side mapping digest used.
- [ ] Ambiguity/exclusion behavior written.
- [ ] `VER-001` inventory row updated.

## Phase 6: Evidence-Quality Verification

Goal: machine-normalize researcher quality labels before SCAE computes leverage.

Implementation tasks:

- Verify source authority, directness, recency, specificity, and classification confidence.
- Produce claimed, normalized, and accepted fields.
- Compute raw/final quality multiplier fields needed by SCAE.
- Preserve correlation groups for SCAE correlated-quality guard.
- Record disagreement reason codes.

Pseudocode:

```python
def verify_quality(classification, provenance):
    claimed = classification.evidence_quality_dimensions
    normalized = {
        "source_authority": infer_source_authority(provenance.source_class),
        "recency": infer_recency(provenance.temporal_gate_metadata),
        "directness": verify_directness(classification, provenance),
        "specificity": verify_specificity(classification, provenance),
        "classification_confidence": classification.classification_confidence,
    }
    accepted = reconcile_quality(claimed, normalized)
    raw_multiplier = quality_multiplier(accepted)
    return quality_verification_slice(
        claimed_quality_fields=claimed,
        machine_normalized_quality_fields=normalized,
        accepted_quality_fields=accepted,
        raw_quality_multiplier=raw_multiplier,
        quality_correlation_groups=infer_quality_groups(provenance),
    )
```

Testing suite:

- Unit: stale evidence normalizes recency lower than claimed.
- Unit: unknown source authority cannot become high authority by claim alone.
- Unit: directness disagreement produces reason code.
- Unit: raw quality multiplier is bounded.
- Integration: every included fixture classification has quality verification.

Completion checklist:

- [ ] Quality verification slice schema written.
- [ ] Accepted quality fields defined.
- [ ] Raw multiplier and correlation group fields written.
- [ ] `VER-002` inventory row updated.

## Phase 7: Adaptive Researcher Escalation

Goal: send more researcher assignments only when the leaf has enough risk or leverage to justify the extra cost.

Implementation tasks:

- Evaluate `researcher-escalation-decision/v1` after primary classification and initial direction/quality verification signals exist.
- Trigger escalation when a leaf is critical/source-of-truth, evidence conflicts, retrieval confidence is low, classification confidence is low, the pre-SCAE leverage proxy is high, or structural unanswerability is claimed.
- Generate extra compact `leaf-research-assignment/v1` packets with `assignment_role="escalation"` or `assignment_role="confirmation"`.
- Enforce `max_concurrent_leaf_researchers_per_case=5`, default one added assignment per triggered leaf, and `max_assignments_for_leaf=3` unless a policy waiver exists.
- Require independent confirmation for structural unanswerability claims and critical/source-of-truth leaves before `VER-004` can mark them SCAE-ready or structurally unanswerable.
- Persist escalation decisions and link every extra assignment back to the decision ref.

Pseudocode:

```python
def evaluate_researcher_escalation(leaf, cert, classifications, direction_slices, quality_slices, policy):
    triggers = []
    if leaf.criticality in {"critical", "source_of_truth"} or leaf.protected_primary_required:
        triggers.append("critical_source_of_truth_leaf")
    if evidence_conflicts(classifications, direction_slices):
        triggers.append("evidence_conflict")
    if cert.retrieval_confidence_bucket == "low":
        triggers.append("low_retrieval_confidence")
    if any(row.classification_confidence == "low" for row in classifications):
        triggers.append("low_classification_confidence")
    leverage = compute_pre_scae_leverage_proxy(leaf, classifications, quality_slices, policy)
    if leverage.bucket == "high":
        triggers.append("high_scae_leverage_proxy")
    if cert.coverage_status == "expansion_exhausted_structurally_unanswerable":
        triggers.append("structural_unanswerability_claimed")

    max_for_leaf = policy.max_assignments_for_leaf(default=3)
    already_assigned = count_leaf_assignments(leaf.leaf_id)
    additional = 0 if not triggers else min(policy.default_additional_assignments(default=1),
                                           max_for_leaf - already_assigned)
    return researcher_escalation_decision(
        leaf_id=leaf.leaf_id,
        trigger_codes=triggers,
        pre_scae_leverage_proxy=leverage.without_probability_fields(),
        escalation_required=additional > 0,
        additional_assignment_count=additional,
        max_assignments_for_leaf=max_for_leaf,
        max_concurrent_leaf_researchers_per_case=5,
    )
```

Testing suite:

- Unit: normal leaf with high retrieval/classification confidence creates no extra assignments.
- Unit: critical/source-of-truth leaf creates an extra confirmation assignment.
- Unit: conflicting evidence creates an extra conflict-resolution assignment.
- Unit: low retrieval confidence creates an extra assignment after expansion certificate exists.
- Unit: low classification confidence creates an extra assignment.
- Unit: high pre-SCAE leverage proxy creates an extra assignment without probability fields.
- Unit: structural unanswerability requires independent confirmation.
- Unit: concurrency cap of five leaf researchers per case is enforced.
- Unit: max assignments per leaf is enforced.
- Unit: zero delivered/already-active escalation assignments cannot mark escalation complete.

Completion checklist:

- [ ] `researcher-escalation-decision/v1` schema written.
- [ ] Escalation trigger policy written.
- [ ] Pre-SCAE leverage proxy written with probability-field rejection.
- [ ] Extra assignment builder linkage written.
- [ ] Concurrency and per-leaf caps written.
- [ ] `CLS-007` inventory row updated.

## Phase 8: SCAE-Readiness Reconciliation

Goal: declare completion only when verified classification slices are ready for SCAE or explicit blockers are recorded.

Implementation tasks:

- Require classification coverage.
- Require provenance completeness.
- Require direction verification for non-neutral classifications.
- Require quality verification for included classifications.
- Require normalized supplemental evidence for supplemental rows.
- Require one-ledger-row-per-claim/source/question/condition-scope readiness.
- Require high-certainty research sufficiency reconciliation for every SCAE-bound leaf.
- Require required researcher escalations to be complete before a leaf can be SCAE-ready.

Pseudocode:

```python
def validate_scae_readiness(matrix, direction_slices, quality_slices, sufficiency_reconciliation, escalation_decisions, qdt):
    errors = []
    if missing_leaf_coverage(matrix, qdt):
        errors.append("leaf_classification_coverage_missing")
    for row in matrix.rows:
        if row.impact_direction != "neutral" and row.id not in direction_slices:
            errors.append(("direction_verification_missing", row.id))
        if row.included_for_scae and row.id not in quality_slices:
            errors.append(("quality_verification_missing", row.id))
        if row.supplemental and not row.normalized_supplemental_ref:
            errors.append(("supplemental_normalization_missing", row.id))
        if row.leaf_id not in sufficiency_reconciliation.scae_ready_leaf_ids:
            errors.append(("research_sufficiency_not_scae_ready", row.leaf_id))
        if escalation_required_but_incomplete(row.leaf_id, escalation_decisions):
            errors.append(("researcher_escalation_incomplete", row.leaf_id))
    return ValidationResult(errors)
```

Testing suite:

- Unit: missing verification blocks SCAE readiness.
- Unit: excluded non-critical row can preserve readiness with reason code if coverage remains sufficient.
- Unit: critical unanswerable leaf triggers policy consequence.
- Unit: missing sufficiency reconciliation blocks SCAE readiness.
- Unit: incomplete required escalation blocks SCAE readiness.
- Integration: fixture run emits SCAE-ready bundle manifest.

Completion checklist:

- [x] SCAE-readiness validator written.
- [x] Completion reconciliation rules written.
- [x] Readiness output artifact/persistence mapped.
- [x] `VER-003` inventory row updated.

## Phase 9: Research Sufficiency Reconciliation

Goal: prove researcher outputs actually covered the prerequisite research required by QDT and retrieval before any classification rows can be marked SCAE-ready.

Implementation tasks:

- Join QDT leaf sufficiency requirements to retrieval sufficiency certificates.
- Join retrieval breadth coverage slices to researcher coverage proofs.
- Join researcher coverage proofs to assigned/reviewed evidence refs.
- Join researcher escalation decisions to primary and extra assignment refs.
- Verify every requirement marked satisfied by retrieval was reviewed by the researcher or explicitly not applicable under structural unanswerability.
- Verify every required escalation is complete before allowing `scae_ready_high_certainty`.
- Reject sidecars that skip required evidence, skip negative checks, omit required value extraction, or attempt to classify from uncertified/macrofallback-only evidence.
- Produce one reconciliation slice per leaf and a bundle-level status for Session 5.

Pseudocode:

```python
def reconcile_research_sufficiency(qdt, retrieval_packet, coverage_proofs, matrix):
    reconciliations = []
    for leaf in qdt.required_leaf_questions:
        cert = retrieval_packet.sufficiency_certificate_for(leaf.leaf_id)
        breadth = retrieval_packet.breadth_coverage_for(leaf.leaf_id)
        proof = coverage_proofs.by_leaf(leaf.leaf_id)
        if cert.coverage_status == "blocked_insufficient_research":
            status = "blocked_insufficient_research"
        elif cert.coverage_status == "expansion_exhausted_structurally_unanswerable":
            status = "structurally_unanswerable" if proof.structural_unanswerability_acknowledged else "blocked_insufficient_research"
        elif required_escalation_incomplete(leaf.leaf_id):
            status = "blocked_insufficient_research"
        elif not proof_covers_certificate_requirements(proof, cert):
            status = "blocked_insufficient_research"
        elif not proof_covers_breadth_coverage(proof, breadth):
            status = "blocked_insufficient_research"
        elif missing_required_value_extractions(leaf, matrix):
            status = "blocked_insufficient_research"
        else:
            status = "scae_ready_high_certainty"
        reconciliations.append(make_reconciliation_slice(leaf, cert, proof, status))
    return reconciliations
```

Testing suite:

- Unit: researcher skipped assigned evidence -> blocked.
- Unit: researcher skipped a required source class, claim family, or source family from breadth coverage -> blocked.
- Unit: researcher skipped required negative check -> blocked.
- Unit: missing required value extraction -> blocked.
- Unit: structural unanswerability certificate requires researcher acknowledgement and provenance.
- Unit: structural unanswerability certificate requires completed independent confirmation if escalation policy requires it.
- Unit: incomplete required escalation blocks SCAE-ready sufficiency.
- Unit: high-certainty certificate plus complete proof yields `scae_ready_high_certainty`.
- Integration: Session 5 receives only rows whose leaf reconciliation is SCAE-ready or structurally unanswerable under policy.

Completion checklist:

- [ ] Research sufficiency reconciliation slice schema written.
- [ ] Coverage proof join implemented or specified.
- [ ] Requirement-level missingness reasons enumerated.
- [ ] Bundle-level SCAE-ready sufficiency status written.
- [ ] `VER-004` inventory row updated.

## End-to-End Completion Checklist

- [ ] Researcher prompts are classification-only.
- [ ] Sidecar schema rejects all probability/fair-value/interval fields.
- [ ] Researcher subagent contexts are isolated and audited before launch.
- [ ] Classification matrix materializes from fixture sidecars.
- [ ] Coverage proofs prove assigned evidence and sufficiency requirements were reviewed.
- [ ] Supplemental evidence normalization works.
- [ ] Direction verification gates non-neutral rows.
- [ ] Evidence-quality verification produces accepted fields and multiplier inputs.
- [ ] Adaptive researcher escalation is trigger-gated, bounded, and complete before SCAE readiness.
- [ ] Completion reconciliation blocks non-ready outputs.
- [ ] Research sufficiency reconciliation blocks thin or skipped research.
- [ ] All Session 4 inventory rows have handoff artifacts and acceptance evidence.
