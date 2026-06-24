# ADS v2 Persistence Migration Order

This is the Session 01 Phase 4 contract baseline for Section 10 persistence. The executable source is `migration_surface_contracts` in `plans/autonomous-decomposition-swarm-feature-inventory.yaml`; this file is the human-readable implementation order.

Runtime integration rule: every write path must have a named table, existing table, view, or explicit external artifact contract before a component writes runtime records. Component sessions own their runtime implementations; Session 1 owns shared contract validation and the Session 1 groups.

## Implementation Order

| Order | Migration Group | Owner | Scope | Destination Contract |
| --- | --- | --- | --- | --- |
| 1 | `MIG-001` | Session 1 | Foundation artifact manifest | `case_artifact_manifest`, `artifact_validation_results` |
| 2 | `MIG-002` | Session 1 | Stage/status/execution/error records | `v2_stage_status_snapshots`, `v2_stage_execution_events`, `v2_pipeline_error_events`, `v2_failure_pattern_groups` |
| 3 | `MIG-013` | Session 1 | Pipeline runner/control/lease records | `ads_pipeline_runs`, `ads_pipeline_control_state`, `ads_case_leases`, `ads_pipeline_loop_iterations`, `ads_pipeline_stop_signals` |
| 4 | `MIG-012` | Session 2 | Existing intake and ADS case contract | existing `markets`, existing `market_snapshots`, `case_intake_handoff_records`, `ads_case_contracts`, `ads-case-contract.json` |
| 5 | `MIG-005` | Session 2 | AMRG candidates, relationships, vector diagnostics | AMRG candidate, vector, relationship, graph-safety, anchor, model-assist, and refresh surfaces |
| 6 | `MIG-003` | Session 3 | QDT/decomposition records | `qdt_decomposition_runs`, `qdt_required_research_questions`, `qdt_leaf_research_sufficiency_requirements`, `qdt_amrg_anchor_dependency_slices`, `question-decomposition.json` |
| 7 | `MIG-004` | Session 3 | Retrieval, evidence, source metadata, breadth, sufficiency | `retrieval-packet.json` plus retrieval evidence, source/claim metadata, breadth, fallback, expansion, missingness, and sufficiency surfaces |
| 8 | `MIG-006` | Session 4 | Researcher assignment, isolation, classification, verification | leaf assignment, isolation audit, classification/provenance, coverage, escalation, verification, supplemental evidence, and reconciliation surfaces |
| 9 | `MIG-007` | Session 5 | SCAE ledger and probability audit | ledger output, log-odds, dependence, branch, conditional, calibration, mechanism-family, missingness, and sufficiency-input surfaces |
| 10 | `MIG-008` | Session 5 | Forecast decision and scoreable prediction bridge | `forecast_decision_records`, existing `market_predictions` |
| 11 | `MIG-009` | Session 5 primary; Session 6 full-trace contributor | Minimal trace and replay records | `training_trace_minimal_pointers`, `v2_replay_manifests`, maturity-only `training_trace_full_materializations` |
| 12 | `MIG-010` | Session 5 | Calibration-debt scoring and resolution records | existing `market_predictions`, `outcome_scoring_records`, existing `evaluator_scorecards`, `v2_replay_result_records` |
| 13 | `MIG-011` | Session 6 | Autonomous optimization maturity lanes | `calibration_candidate_records`, `calibration_lane_pointer_records`, `policy_rollback_events`, `effective_tuning_profile_context.json` |

## Cutover Versus Later Work

Live-cutover groups:
`MIG-001`, `MIG-002`, `MIG-013`, `MIG-012`, `MIG-005`, `MIG-003`, `MIG-004`, `MIG-006`, `MIG-007`, `MIG-008`, `MIG-009`.

Calibration-debt clearance group:
`MIG-010`.

Autonomous optimization maturity group:
`MIG-011`.

Maturity-only surfaces are not required for direct v2 live cutover: `training_trace_full_materializations`, `calibration_candidate_records`, `calibration_lane_pointer_records`, `policy_rollback_events`, and autonomous policy promotion outputs. They remain non-authoritative unless promoted through the policy pointer contract.

## Contract Checks

- `python3 plans/check_dependency_gates.py` validates every migration group has ordered destination coverage for each declared write path.
- Missing destination coverage fails inventory validation even if normal feature dependencies are ready.
- `--report-only` can summarize expected downstream blockers, but validation errors still fail.
- A component session that needs a new write path must add it to the executable inventory and schema-name map through its own row or a phase report before runtime integration.
