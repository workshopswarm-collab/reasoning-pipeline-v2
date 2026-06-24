# Autonomous Decomposition-Swarm Feature Inventory

This is the starter inventory for converting the architecture spec into async implementation work. Keep rows small: each row should be implementable, testable, and owned by one development session.

Status values:
`not_started`, `contracting`, `in_progress`, `blocked`, `ready_for_integration`, `done`

## Acceptance Evidence

- `FND-001`: done on 2026-06-24. Phase 0 audit verified all Session 1 owned IDs are present exactly once in the inventory, ownership is correct, master anchors are current, and the Session 1 plan excludes other sessions' runtime behavior.
- `FND-001`: Phase 1 dependency gate/inventory tracking acceptance completed on 2026-06-24. Evidence: dependency gate validates inventory shape, unknown dependencies, cycles, waiver shape/expiry, runtime blocking, fixture-mode starts, owner/evidence update rules, Markdown/YAML feature sync, and the phase-report convention.

## Inventory Coordination Contract

The Markdown inventory is the human status board. `plans/autonomous-decomposition-swarm-feature-inventory.yaml` is the executable dependency source and must remain JSON-compatible.

Ownership rules:

- Session 1 owns shared coordination files and direct updates for `FND-*`, `AUTO-*`, `MIG-001`, `MIG-002`, and `MIG-013`.
- Component sessions update only rows they own when they can include acceptance evidence and avoid shared-file conflicts.
- A row may move to `ready_for_integration` or `done` only when acceptance evidence is recorded.
- Cross-session dependency, owner, schema-name, script-placement, blocker, or fixture changes are proposed through phase reports when concurrent shared-file edits would conflict.

Waiver rules:

- Waivers live in the executable inventory's `waivers` list.
- Every waiver requires `dependency_id`, `target_id`, `owner`, `reason`, and `expires_on`.
- Expired, malformed, or unknown-target waivers are invalid.
- Waivers are temporary dependency gates only; they cannot create a second forecast authority or bypass SCAE-only production probability.

Async phase-report rules:

- Sessions 2-5 write conflict-safe reports under `plans/phase-reports/` when shared inventory/maps need reconciliation.
- Report filenames use `session-0N-phase-M-short-slug.md`.
- Session 1/coordinator reconciles reviewed reports into shared inventory, maps, matrices, and dependency gates in a separate commit.

## Persistence Migration Inventory

These migration groups are the data backbone for replay, scoring, calibration, and future parameter tuning. `FND-004` owns the shared migration contract and ordering, but each worker session owns the write paths for the records it produces. Runtime integration must not proceed for a component unless its owned migration groups have a named table, schema, or explicit external artifact contract.

| Migration ID | Stage | Owner | Feature Rows | Write Path Contract | Tuning Purpose | Status |
| --- | --- | --- | --- | --- | --- | --- |
| MIG-001 | foundation | Session 1 | `FND-003`, `FND-004` | `write_artifact_manifest()` | Records artifact type, schema version, hash, timestamp, producer, and lineage so old forecasts can be replayed exactly. | not_started |
| MIG-002 | foundation | Session 1 | `FND-002`, `FND-006` | `write_stage_status()`, `write_stage_execution_event()`, `write_pipeline_error_event()` | Records stage status, stage-wrapper lifecycle events, safe log refs, replay commands, and where cases fail, block, downgrade, or retry so failure rates, deadlocks, and retry policy can be tuned. | not_started |
| MIG-013 | v2_live_cutover | Session 1 | `AUTO-001` to `AUTO-006` | `write_pipeline_run()`, `write_pipeline_control_state()`, `acquire_case_lease()`, `write_pipeline_loop_iteration()`, `write_pipeline_stop_signal()`, `release_case_lease()` | Records continuous automation runs, durable enable/disable state, case leases, loop iterations, stop/drain requests, empty-queue waits, retries, and terminal outcomes so the pipeline can run end-to-end repeatedly without duplicate case execution. | not_started |
| MIG-012 | v2_live_cutover | Session 2 | `CASE-001`, `CASE-002` | `write_case_intake_handoff()`, `write_ads_case_contract()` | Bridges the existing intake pipeline into ADS by binding current `markets`/`market_snapshots` rows, source payload hashes, dispatch identity, forecast timestamp, source cutoff, and raw intake provenance into the canonical case contract. | not_started |
| MIG-003 | v2_live_cutover | Session 3 | `QDT-001` to `QDT-005`, `MODEL-002` | `write_decomposition_run()`, `write_qdt_research_sufficiency_requirements()` | Stores selected QDT, leaves, branches, dependency groups, AMRG usage, per-leaf research sufficiency requirements, canonical prompt/schema provenance, and model provenance so decomposition shapes and research contracts can be evaluated. | not_started |
| MIG-004 | v2_live_cutover | Session 3 | `RET-001` to `RET-011` | `write_retrieval_packet()`, `write_retrieval_evidence_items()`, `write_retrieval_evidence_chunk_slices()`, `write_native_research_attempts()`, `write_browser_retrieval_attempts()`, `write_browser_search_provider_diagnostics()`, `write_source_metadata_classifier_slices()`, `write_source_metadata_resolution_slices()`, `write_atomic_claim_candidate_slices()`, `write_claim_family_resolution_slices()`, `write_metadata_fill_diagnostics()`, `write_retrieval_quality_slices()`, `write_evidence_provenance_slices()`, `write_retrieval_breadth_profile()`, `write_retrieval_breadth_coverage_slices()`, `write_contradiction_search_attempts()`, `write_negative_check_attempts()`, `write_source_access_and_missingness_slices()`, `write_retrieval_fallback_state()`, `write_retrieval_expansion_attempts()`, `write_research_sufficiency_certificate()` | Stores retrieval packets, admitted evidence items, chunk/span refs, GPT-native research attempts, OpenClaw browser capture and provider diagnostics, classifier/parser assist slices, deterministic source metadata decisions, atomic claim candidates, claim-family resolutions, metadata fill-rate diagnostics, retrieval quality, evidence provenance, source/claim/source-family/source-class fields, timestamps, retrieval breadth profiles, contradiction/negative-check attempts, missingness, fallback state, expansion attempts, and high-certainty sufficiency certificates for retrieval/source-coverage tuning. | not_started |
| MIG-005 | v2_live_cutover | Session 2 | `AMRG-001` to `AMRG-009` | `write_related_market_context()`, `write_amrg_vector_descriptors()`, `write_amrg_vector_index_snapshot()`, `write_amrg_vector_neighbor_candidates()` | Stores related-market candidates, local vector descriptors, vector index snapshots, vector-neighbor candidates, edge types, timing validation, anchor eligibility, refresh events, and model-assist provenance. | not_started |
| MIG-006 | v2_live_cutover | Session 4 | `CLS-001` to `CLS-008`, `VER-001` to `VER-004`, `MODEL-003` | `write_leaf_research_assignments()`, `write_researcher_context_isolation_audits()`, `write_researcher_classifications()`, `write_verification_slices()`, `write_researcher_coverage_proofs()`, `write_researcher_escalation_decisions()`, `write_research_sufficiency_reconciliation()` | Stores compact per-leaf assignment packets, context-isolation audit records, leaf classifications, extracted values, quality fields, evidence-review coverage proofs, trigger-gated researcher escalation decisions, sufficiency reconciliation, side-mapping checks, verifier results, and researcher model provenance. | not_started |
| MIG-007 | v2_live_cutover | Session 5 | `SCAE-001` to `SCAE-013` | `write_scae_ledger()`, `write_scae_research_sufficiency_inputs()` | Stores prior, signed log-odds updates, caps, netting, cross-leaf dependence, branch sub-ledgers, research sufficiency intake, intervals, calibration context, and final probability fields. | not_started |
| MIG-008 | v2_live_cutover | Session 5 | `SYN-001`, `DEC-001`, `PERSIST-001`, `PERSIST-002` | `write_forecast_decision()`, `record_market_prediction()`, `record_prediction_with_snapshot()` | Stores only SCAE `production_forecast_prob` plus forecast validity/actionability status, and writes the scoreable prediction-time market baseline bridge into existing `market_predictions`. | not_started |
| MIG-009 | v2_live_cutover, calibration_debt_clearance | Session 5 primary; Session 6 contributor for `TRACE-002` | `TRACE-001`, `TRACE-002`, `MODEL-004`, `REPLAY-001` | `write_minimal_training_trace()`, `write_replay_manifest()`, `write_full_training_trace_materialization()` | Stores hashes and pointers for first-100+ runs and later full materializations without giving traces live forecast authority. | not_started |
| MIG-010 | calibration_debt_clearance | Session 5 | `REPLAY-001`, `SCORE-001`, `CAL-001` | `write_resolution_score()`, `settle_market_outcome()`, `brier_score_report()` | Stores resolved outcome, pipeline Brier, prediction-time market baseline Brier, Brier edge, reliability bucket, and resolution provenance using the existing `market_predictions` scoring spine and evaluator scorecards. | not_started |
| MIG-011 | autonomous_optimization_maturity | Session 6 | `CAL-002` to `CAL-005`, `POL-001` | `write_calibration_candidate()`, `promote_policy_pointer()`, `write_policy_rollback_event()` | Stores candidate policy snapshots, lane ownership, canary state, active pointers, rollback pointers, component diagnostics, and promotion decisions. | not_started |

## Layer 0: Shared Foundations

| Feature ID | Stage | Component | Blocking | Owner | Dependencies | Output | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FND-001 | foundation | Planning | foundation_blocker | Session 1 | none | Canonical feature inventory and dependency DAG | done |
| FND-002 | foundation | Control plane | cutover_blocker | Session 1 | FND-001 | v2 stage vocabulary, status contract, and execution-event stream | not_started |
| FND-003 | foundation | Artifacts | cutover_blocker | Session 1 | FND-001 | Artifact manifest schema and validator | not_started |
| FND-004 | foundation | Persistence | cutover_blocker | Session 1 | FND-001 | Section 10 migration/schema plan | not_started |
| FND-005 | foundation | Fixtures | integration_blocker | Session 1 | FND-003, FND-004 | Golden fixture registry and runner | not_started |
| FND-006 | foundation | Validation | cutover_blocker | Session 1 | FND-002, FND-003 | Fail-closed validation, safe stage execution logging, and error events | not_started |
| FND-007 | foundation | Training trace | cutover_blocker | Session 1 | FND-003, FND-004 | Minimal trace pointer contract | not_started |
| AUTO-001 | v2_live_cutover | Automation runner | cutover_blocker | Session 1 | FND-002, FND-003, FND-004 | Orchestrator continuous pipeline runner contract with run identity, mode, stop/drain controls, and stage order | not_started |
| AUTO-002 | v2_live_cutover | Case leasing | cutover_blocker | Session 1 | AUTO-001, CASE-001, FND-004 | Unique eligible-case selector and lease/idempotency guard over existing case pipeline DB rows | not_started |
| AUTO-003 | v2_live_cutover | Dispatch state machine | cutover_blocker | Session 1 | AUTO-002, CASE-002, QDT-001, CLS-001, SCAE-012, PERSIST-001 | End-to-end Orchestrator state machine from leased case through SCAE probability and forecast persistence | not_started |
| AUTO-004 | v2_live_cutover | Retry and stop policy | cutover_blocker | Session 1 | AUTO-003, FND-006 | Retry/backoff, soft-fail/quarantine, stop-after-current, drain, and stuck-lease recovery policy | not_started |
| AUTO-005 | v2_live_cutover | Continuous loop fixture | integration_blocker | Session 1 | AUTO-004, FND-005, PERSIST-002 | Automated two-case fixture proving loop continues to next unique case and stops cleanly on request | not_started |
| AUTO-006 | v2_live_cutover | Manual enable switch | cutover_blocker | Session 1 | AUTO-001, AUTO-002, FND-004 | Durable global `pipeline_enabled` control state checked before runner start/restart and before every new case lease | not_started |

## Layer 1: Pre-Decomposition Case Context

| Feature ID | Stage | Component | Blocking | Owner | Dependencies | Output | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CASE-001 | v2_live_cutover | Intake adapter | cutover_blocker | Session 2 | FND-003, FND-004 | Existing case pipeline source adapter over `markets` and `market_snapshots` | not_started |
| CASE-002 | v2_live_cutover | ADS case contract | cutover_blocker | Session 2 | CASE-001, FND-003 | `ads-case-contract/v1` with dispatch identity, source cutoff, snapshot binding, and raw intake provenance | not_started |
| CTX-001 | v2_live_cutover | Evidence packet | cutover_blocker | Session 2 | CASE-002, FND-003 | Evidence packet v2 contract | not_started |
| CTX-002 | v2_live_cutover | Market family | cutover_blocker | Session 2 | CTX-001, FND-004 | Family-aware binary child metadata | not_started |
| CTX-003 | v2_live_cutover | Market prior | cutover_blocker | Session 2 | CTX-001, FND-004 | Prior-reliability input surfaces | not_started |
| POL-001 | foundation | Policy | foundation_blocker | Session 2 | FND-004 | Tunable registry metadata contract | not_started |
| POL-002 | v2_live_cutover | Regime tags | integration_blocker | Session 2 | CTX-001, POL-001 | Deterministic market-regime tags | not_started |
| POL-003 | v2_live_cutover | Profile resolver | integration_blocker | Session 2 | POL-001, POL-002 | `effective_tuning_profile_context.json` | not_started |
| MODEL-001 | v2_live_cutover | Model lanes | cutover_blocker | Session 2 | POL-001, FND-003 | Model lane policy artifact with `gpt-5.5-high` decomposer/researcher/native-research defaults plus OpenAI OAuth-routed `openai/gpt-5.4-mini` source metadata classifier assist lane | not_started |

## Layer 2: AMRG

| Feature ID | Stage | Component | Blocking | Owner | Dependencies | Output | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AMRG-001 | v2_live_cutover | AMRG | cutover_blocker | Session 2 | CTX-001 | Active-safe candidate pool | not_started |
| AMRG-009 | v2_live_cutover | AMRG vectorization | non_blocking_candidate_source | Session 2 | CTX-001, MODEL-001, FND-003 | Local Ollama-routed `BAAI/bge-base-en-v1.5` active-market vector index and weak-context neighbor candidates; unavailable model/index records diagnostic and does not block AMRG | not_started |
| AMRG-002 | v2_live_cutover | AMRG | cutover_blocker | Session 2 | AMRG-001, FND-003 | `related-live-market-context.json` or waiver | not_started |
| AMRG-003 | v2_live_cutover | AMRG | integration_blocker | Session 2 | AMRG-002 | Relationship typing and timing alignment | not_started |
| AMRG-004 | v2_live_cutover | AMRG model assist | integration_blocker | Session 2 | AMRG-001, AMRG-002 | Advisory model-assist packet and output schema | not_started |
| AMRG-005 | v2_live_cutover | AMRG persistence | cutover_blocker | Session 2 | AMRG-002, FND-004 | Relationship, graph-safety, refresh slices | not_started |
| AMRG-006 | v2_live_cutover | AMRG refresh | integration_blocker | Session 2 | AMRG-003, AMRG-005 | Refresh lifecycle and stale downgrade | not_started |
| AMRG-007 | autonomous_optimization_maturity | AMRG reuse | maturity_only | Session 2 | AMRG-005, RET-004 | Shared retrieval/classification cache eligibility | not_started |
| AMRG-008 | v2_live_cutover | AMRG anchors | integration_blocker | Session 2 | AMRG-003, QDT-004 | Strict-precedence anchor validation | not_started |

## Layer 3: Decomposition and Retrieval

| Feature ID | Stage | Component | Blocking | Owner | Dependencies | Output | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| QDT-001 | v2_live_cutover | Decomposer | cutover_blocker | Session 3 | CASE-002, CTX-001, POL-003, AMRG-002 | Artifact-path handoff contract including ADS case contract manifest | not_started |
| QDT-002 | v2_live_cutover | Decomposer | cutover_blocker | Session 3 | QDT-001, FND-003 | `question-decomposition.json` schema | not_started |
| QDT-003 | v2_live_cutover | Decomposer validation | cutover_blocker | Session 3 | QDT-002 | Deterministic QDT structural validator | not_started |
| QDT-004 | v2_live_cutover | Decomposer AMRG | integration_blocker | Session 3 | QDT-002, AMRG-003 | AMRG anchor dependency contract | not_started |
| QDT-005 | v2_live_cutover | Research sufficiency | cutover_blocker | Session 3 | QDT-002, QDT-003, POL-003 | Per-leaf high-certainty research sufficiency requirements in canonical QDT template | not_started |
| MODEL-002 | v2_live_cutover | Decomposer model lane | cutover_blocker | Session 3 | MODEL-001, QDT-001 | Resolve and record `gpt-5.5-high` decomposer QDT model lane | not_started |
| RET-001 | v2_live_cutover | Retrieval | cutover_blocker | Session 3 | QDT-002, FND-003 | Retrieval packet schema | not_started |
| RET-002 | v2_live_cutover | Retrieval validation | cutover_blocker | Session 3 | RET-001 | Strict temporal isolation validator | not_started |
| RET-003 | v2_live_cutover | Retrieval quality | integration_blocker | Session 3 | RET-001, FND-004 | Retrieval quality scoring slices | not_started |
| RET-004 | v2_live_cutover | Retrieval provenance | cutover_blocker | Session 3 | RET-001, FND-004 | Source, browser-capture, claim-family, source-family, independence provenance | not_started |
| RET-005 | v2_live_cutover | Source access | integration_blocker | Session 3 | RET-004 | Protected-primary and missingness candidates | not_started |
| RET-006 | v2_live_cutover | Retrieval fallback | integration_blocker | Session 3 | RET-002, RET-003 | Starvation expansion and macro fallback | not_started |
| RET-007 | v2_live_cutover | Local models | integration_blocker | Session 3 | RET-001 | Embedding/reranker preflight and resource caps | not_started |
| RET-010 | v2_live_cutover | Native research transport and metadata resolver | cutover_blocker | Session 3 | MODEL-001, RET-001, RET-002, RET-004, FND-003 | GPT-5.5 native research candidate discovery plus deterministic source metadata resolver for source-class, source-family, claim-family, and temporal-safety fields | not_started |
| RET-011 | v2_live_cutover | Source metadata classifier assist | cutover_blocker | Session 3 | MODEL-001, RET-004, RET-010, FND-003 | OpenAI OAuth-routed `openai/gpt-5.4-mini` compact classifier lane for source-class, source-family hints, claim tuples, syndication hints, and visible-date candidates; accepted only through validator rules and never enough for protected-primary or temporal safety by itself | not_started |
| RET-009 | v2_live_cutover | Retrieval breadth | cutover_blocker | Session 3 | QDT-005, RET-001, RET-002, RET-003, RET-004, RET-005, RET-006, RET-010, RET-011, POL-003 | `retrieval-breadth-profile/v1` and per-leaf breadth coverage slices for source-class, claim-family, source-family, freshness, contradiction search, negative checks, and protected-primary requirements | not_started |
| RET-008 | v2_live_cutover | Research sufficiency | cutover_blocker | Session 3 | QDT-005, RET-002, RET-003, RET-004, RET-005, RET-006, RET-007, RET-009 | High-certainty retrieval sufficiency loop and per-leaf certificate before researcher dispatch | not_started |

## Layer 4: Researcher Classification and Verification

| Feature ID | Stage | Component | Blocking | Owner | Dependencies | Output | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CLS-001 | v2_live_cutover | Researcher prompt | cutover_blocker | Session 4 | QDT-002, QDT-005, RET-001, RET-008 | NLI classification prompt contract | not_started |
| CLS-006 | v2_live_cutover | Leaf assignment artifact | cutover_blocker | Session 4 | CLS-001, QDT-005, RET-008, MODEL-003, FND-003 | Compact `leaf-research-assignment/v1` subagent packet using refs instead of duplicated evidence text | not_started |
| CLS-008 | v2_live_cutover | Researcher context isolation | cutover_blocker | Session 4 | CLS-006, MODEL-003, FND-003, FND-006 | Per-subagent context silo contract and audit proving leaf researchers cannot see sibling assignments, peer sidecars, aggregate conclusions, SCAE refs, or replay/scoring outcomes | not_started |
| CLS-002 | v2_live_cutover | Sidecar schema | cutover_blocker | Session 4 | CLS-001, FND-003 | No-probability sidecar schema | not_started |
| CLS-003 | v2_live_cutover | Classification matrix | cutover_blocker | Session 4 | CLS-002, RET-004 | Evidence classification matrix | not_started |
| CLS-004 | v2_live_cutover | Supplemental evidence | integration_blocker | Session 4 | CLS-003, RET-004 | Supplemental evidence normalization boundary | not_started |
| CLS-005 | v2_live_cutover | Research coverage | cutover_blocker | Session 4 | CLS-002, CLS-003, CLS-006, CLS-008, RET-008 | Researcher evidence-review coverage proof against assignment refs, context-isolation audit, and sufficiency requirements | not_started |
| CLS-007 | v2_live_cutover | Adaptive researcher escalation | cutover_blocker | Session 4 | CLS-003, CLS-005, VER-001, VER-002, RET-008, QDT-005, POL-003 | Trigger-gated extra leaf-research assignments for critical/source-of-truth leaves, evidence conflicts, low retrieval confidence, low classification confidence, high pre-SCAE leverage proxy, and structural unanswerability claims | not_started |
| MODEL-003 | v2_live_cutover | Researcher model lane | cutover_blocker | Session 4 | MODEL-001, CLS-001 | Resolve and record `gpt-5.5-high` researcher leaf NLI model lane | not_started |
| VER-001 | v2_live_cutover | Direction verification | cutover_blocker | Session 4 | CLS-003, FND-004 | Direction verification slices | not_started |
| VER-002 | v2_live_cutover | Quality verification | cutover_blocker | Session 4 | CLS-003, FND-004 | Evidence-quality verification slices | not_started |
| VER-003 | v2_live_cutover | Completion reconciliation | cutover_blocker | Session 4 | CLS-002, CLS-005, VER-001, VER-002 | SCAE-readiness validation | not_started |
| VER-004 | v2_live_cutover | Research sufficiency reconciliation | cutover_blocker | Session 4 | CLS-005, CLS-007, RET-008, VER-001, VER-002, VER-003 | Verified high-certainty research sufficiency bundle for SCAE after required researcher escalations are resolved | not_started |

## Layer 5: SCAE, Synthesis, Decision

| Feature ID | Stage | Component | Blocking | Owner | Dependencies | Output | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SCAE-001 | v2_live_cutover | SCAE policy | cutover_blocker | Session 5 | FND-004, POL-003 | Base policy and probability taxonomy | not_started |
| SCAE-002 | v2_live_cutover | SCAE prior | cutover_blocker | Session 5 | CTX-003, SCAE-001 | Prior odds and market-assimilation context | not_started |
| SCAE-003 | v2_live_cutover | SCAE evidence | cutover_blocker | Session 5 | VER-001, VER-002, RET-003, SCAE-001 | Evidence delta mapping | not_started |
| SCAE-004 | v2_live_cutover | SCAE caps | cutover_blocker | Session 5 | SCAE-003 | Correlated-quality guard and cap stack | not_started |
| SCAE-005 | v2_live_cutover | SCAE netting | cutover_blocker | Session 5 | SCAE-003, RET-004 | Intra-leaf representative cluster netting | not_started |
| SCAE-006 | v2_live_cutover | SCAE dependence | cutover_blocker | Session 5 | SCAE-005, RET-004 | Cross-leaf dependence guard | not_started |
| SCAE-007 | v2_live_cutover | SCAE branches | integration_blocker | Session 5 | SCAE-006, QDT-002 | Branch sub-ledgers | not_started |
| SCAE-008 | v2_live_cutover | SCAE temporal | integration_blocker | Session 5 | SCAE-003, RET-005 | Missingness and survival/no-catalyst policy | not_started |
| SCAE-009 | v2_live_cutover | SCAE family | integration_blocker | Session 5 | CTX-002, SCAE-002 | Binary-child diagnostics and displacement signals | not_started |
| SCAE-010 | v2_live_cutover | SCAE AMRG | integration_blocker | Session 5 | AMRG-008, QDT-004, SCAE-007 | Conditional branch recombination | not_started |
| SCAE-011 | v2_live_cutover | SCAE interval | cutover_blocker | Session 5 | SCAE-004, SCAE-006 | Deterministic logit interval builder | not_started |
| SCAE-013 | v2_live_cutover | SCAE sufficiency gate | cutover_blocker | Session 5 | VER-004, SCAE-011 | Research sufficiency certificate intake and high-certainty forecast-validity guard | not_started |
| SCAE-012 | v2_live_cutover | SCAE calibration debt | cutover_blocker | Session 5 | SCAE-011, SCAE-013 | Identity calibration and debt controls | not_started |
| SYN-001 | v2_live_cutover | Synthesis | cutover_blocker | Session 5 | SCAE-012 | Qualitative annotation only, no probability override | not_started |
| DEC-001 | v2_live_cutover | Decision | cutover_blocker | Session 5 | SCAE-012 | Decision/Execution Gate consumes SCAE probability only | not_started |
| PERSIST-001 | v2_live_cutover | Forecast persistence | cutover_blocker | Session 5 | DEC-001, SCAE-012 | Production forecast persistence from SCAE only | not_started |
| PERSIST-002 | v2_live_cutover | Prediction scoring bridge | cutover_blocker | Session 5 | PERSIST-001, CASE-002 | Persist SCAE forecast to existing `market_predictions` with prediction-time market snapshot baseline provenance | not_started |

## Layer 6: Replay, Calibration, and Maturity

| Feature ID | Stage | Component | Blocking | Owner | Dependencies | Output | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TRACE-001 | v2_live_cutover | Training trace | cutover_blocker | Session 5 | FND-007, FND-003 | Synchronous minimal trace pointer | not_started |
| TRACE-002 | autonomous_optimization_maturity | Training trace | maturity_only | Session 6 | TRACE-001, REPLAY-001 | Async full trace materialization | not_started |
| REPLAY-001 | calibration_debt_clearance | Replay | foundation_blocker | Session 5 | TRACE-001, FND-004 | First-100 replay manifests and result records | not_started |
| SCORE-001 | calibration_debt_clearance | Outcome scoring | foundation_blocker | Session 5 | PERSIST-002, REPLAY-001 | Brier scoring and prediction-time market baseline comparison via existing `market_predictions` and `brier_score_report()` | not_started |
| CAL-001 | calibration_debt_clearance | Calibration debt | foundation_blocker | Session 5 | REPLAY-001, SCAE-012, SCORE-001 | Explicit debt-clearance gates | not_started |
| CAL-002 | autonomous_optimization_maturity | Calibration lanes | maturity_only | Session 6 | CAL-001, POL-001 | Lane queues, pointers, canaries, health, rollback | not_started |
| CAL-003 | autonomous_optimization_maturity | Retrieval calibration | maturity_only | Session 6 | CAL-002, RET-003 | Retrieval-policy calibration snapshots | not_started |
| CAL-004 | autonomous_optimization_maturity | Profile calibration | maturity_only | Session 6 | CAL-002, QDT-003, DEC-001 | Decomposer and decision/actionability profile lanes | not_started |
| CAL-005 | autonomous_optimization_maturity | Optimization maturity | maturity_only | Session 6 | CAL-002, CAL-003, CAL-004 | Autonomous optimization maturity gate | not_started |

## Layer 7: Model Lane Provenance

| Feature ID | Stage | Component | Blocking | Owner | Dependencies | Output | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MODEL-004 | v2_live_cutover | Model provenance trace | cutover_blocker | Session 5 | MODEL-002, MODEL-003, TRACE-001 | Trace resolved model IDs, policy refs, prompt hashes, and schema versions | not_started |

## First Integration Target

The first shared target is a fixture-only vertical slice:

1. Automation runner fixture with unique case lease and stop-after-current support.
2. Evidence packet v2 fixture.
3. AMRG no-related-context waiver or weak-context artifact.
4. Valid depth-2 QDT artifact.
5. Retrieval packet with temporal isolation metadata.
6. Researcher sidecar fixture with NLI classifications and no probability fields.
7. Researcher coverage proof and high-certainty sufficiency reconciliation are present before SCAE.
8. Direction and quality verification slices.
9. SCAE ledger with all required probability fields and research sufficiency context.
10. Synthesis annotation that cannot override probability.
11. Decision context that persists only `production_forecast_prob`.
12. Decomposer, researcher, native-research, and source-metadata-classifier artifacts record resolved model lanes, policy refs, prompt hashes, and schema versions.
13. Minimal training trace pointer and replay manifest include model provenance.
14. Two-case loop fixture proves the runner releases the first case and selects a second unique case without duplicate prediction rows.
