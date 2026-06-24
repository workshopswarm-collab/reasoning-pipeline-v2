# Autonomous Decomposition-Swarm Implementation Plan

Source spec:
`/Users/agent2/.openclaw/media/inbound/autonomous-decomposition-swarm-architecture-spec---dbda0f1c----c13d6bea-f02f-4991-8d2c-d69ad5a7dc5a.md`

## Planning Posture

This is a direct-cutover architecture, but implementation should not begin as a direct live rewrite. Build it as a sequence of contract-validating foundations, then stage implementations, then live cutover gates. Section 1.1, Section 10, and Section 18 are authoritative:

- SCAE is the only live numeric forecast authority.
- Researcher, synthesis, decision, replay, canary, evaluator, and training-trace outputs are non-authoritative for live probability.
- Any persisted slice or record named by implementation must exist in the Section 10 persistence inventory or be added to the inventory before implementation.
- `v2_live_cutover`, `calibration_debt_clearance`, and `autonomous_optimization_maturity` are separate stages.

The current Orchestrator repo is much smaller than the target spec. It currently has intake, SQLite/predquant foundations, a basic foundation migration, and health scripts. The first implementation work should therefore create contracts, schemas, migrations, stage status and execution-event logging, fixtures, and artifact validation before building AMRG, retrieval, SCAE, or evaluator behavior.

## Runtime Agent and Script Placement Contract

OpenClaw agent workspaces created for v2 runtime specialization:

| Runtime role | OpenClaw agent/workspace | Responsibility |
| --- | --- | --- |
| Orchestrator | `/Users/agent2/.openclaw/orchestrator` | Pipeline management, case intake, stage/status, artifact manifests, handoffs, waking Decomposer, waking Researcher Swarm, kicking SCAE, synthesis/decision routing, and post-SCAE operations. |
| ADS Decomposer | `/Users/agent2/.openclaw/decomposer` | Conduct market decomposition and create the canonical QDT. |
| ADS Researcher Swarm | `/Users/agent2/.openclaw/researcher-swarm` | Create and coordinate researcher subagents for QDT leaf questions, conduct leaf research, and produce verified classification artifacts. |
| SCAE | `/Users/agent2/.openclaw/SCAE` | Deterministic SCAE ledger, probability fields, netting, interval, calibration-debt controls, and scoreable forecast persistence helpers. |

Script placement is authoritative in `plans/autonomous-decomposition-swarm-script-placement-map.md`. Before creating any new ADS runtime script, workers must add or confirm its exact path in that map.

Default placement rules:

1. Orchestrator-owned management and handoff scripts go under `/Users/agent2/.openclaw/orchestrator/scripts`.
2. Decomposer-owned QDT scripts go under `/Users/agent2/.openclaw/decomposer/scripts`.
3. Researcher-swarm-owned leaf research, retrieval, subagent, classification, and verification scripts go under `/Users/agent2/.openclaw/researcher-swarm/scripts`.
4. SCAE-owned deterministic ledger scripts go under `/Users/agent2/.openclaw/SCAE/scripts`.
5. Newly created scripts that do not clearly belong to Decomposer, Researcher Swarm, or SCAE default to Orchestrator.

## Continuous Automation Contract

The v2 pipeline must be able to run end-to-end without routine human intervention. Orchestrator owns the continuous automation loop:

```text
enable pipeline and start runner
 -> select one eligible unique market/case from existing intake DB
 -> acquire case lease and create ADS case contract
 -> build evidence/profile/AMRG context
 -> wake Decomposer and validate QDT
 -> wake Researcher Swarm and validate retrieval/research/verification bundle
 -> kick SCAE and validate ledger
 -> run synthesis annotation and decision gate
 -> persist SCAE production forecast and prediction-time market baseline
 -> write trace/replay/scoring refs
 -> release lease
 -> select next eligible case
 -> continue until disabled, stop/drain signal, or no eligible cases
```

Automation is not another forecast authority. It is the Orchestrator-owned state machine that calls the stage owners, records stage status, stage execution events, and error events, enforces dependency gates, and prevents duplicate in-flight work. Specialist agents can reject malformed packets and return structured failures, but they do not select global next work or advance the pipeline state machine.

The runner must support:

- Durable manual enable/disable control: `pipeline_enabled=false` prevents runner start/restart from acquiring new cases and blocks lease acquisition before every iteration.
- Unique case leasing over existing `markets` / `market_snapshots` sources so the same active market is not processed twice concurrently.
- Configurable modes: fixture, non-executing canary, calibration-debt production, and stopped/draining.
- Stop controls: stop-before-next-case, stop-after-current-case, and immediate safe drain that leaves the active case in a recoverable state. Disabling the pipeline should default to no new leases and may optionally write a stop-after-current or safe-drain signal.
- Empty-queue behavior: sleep/backoff or exit according to policy, without marking failure.
- Retry/backoff policy separated by stage failure class: transient gateway/session errors, source access failures, schema validation failures, and non-retryable contract failures.
- Idempotent restart: a runner can recover a leased case from the last valid stage status without duplicating SCAE forecast writes.
- Continuous traceability through `MIG-013` control-state, run, lease, loop-iteration, stop-signal, and release records.

## ADS Case Contract

The ADS case contract is the canonical passover from the existing case/market intake pipeline into the decomposition system. It is not a legacy/v1 object. It is the current v2 entry contract for real markets.

`ads-case-contract/v1` binds:

- Existing intake source rows: `markets` and the selected `market_snapshots` row from `scripts/predquant/sqlite_store.py`.
- Stable market identity: platform, internal SQLite `market_id`, external market ID, slug/title, close/resolve timestamps, and source payload hash.
- Stable case identity: `case_key`, `case_id`, `dispatch_id`, `prediction_run_id`, and `forecast_artifact_id`.
- Forecast-time boundary: `forecast_timestamp`, `source_cutoff_timestamp`, selected market snapshot observed time, and snapshot age policy.
- Raw provenance: database path/ref, source table names, source row IDs, raw payload hash, ingestion runner/schema version, code version when available, and artifact manifest IDs.
- Downstream handoff refs: evidence packet, profile context, AMRG artifact/waiver, QDT, retrieval packet, verification bundle, SCAE ledger, decision record, and scoreable prediction row.

The evidence packet is derived from this case contract. Decomposition must not read directly from ad hoc intake rows or scraper payloads once the case contract exists.

## Feature Inventory Method

Maintain one canonical feature inventory in this folder before coding large components. Suggested columns:

| Column | Purpose |
| --- | --- |
| `feature_id` | Stable ID, e.g. `FND-001`, `AMRG-003`, `SCAE-013`. |
| `spec_refs` | Section and line/range reference from the source spec. |
| `stage` | `foundation`, `v2_live_cutover`, `calibration_debt_clearance`, or `autonomous_optimization_maturity`. |
| `component` | Control plane, evidence packet, AMRG, decomposer, retrieval, researcher, verifier, SCAE, synthesis, decision, evaluator, training trace. |
| `feature` | One implementable behavior or contract. |
| `blocking_level` | `cutover_blocker`, `foundation_blocker`, `integration_blocker`, `maturity_only`, or `non_goal`. |
| `inputs` | Required artifacts, tables, policy refs, case fields, or upstream stages. |
| `outputs` | Artifacts, tables, status slices, prompts, or validation reports. |
| `persistence_surface` | Required Section 10 table, schema, or external artifact. |
| `dependencies` | Feature IDs that must land first. |
| `owner_session` | One of the six async sessions below. |
| `acceptance` | Concrete validation, fixture, migration, or test criteria. |
| `status` | `not_started`, `contracting`, `in_progress`, `blocked`, `ready_for_integration`, `done`. |

Inventory rules:

1. Do not let a task become "build AMRG" or "build SCAE"; split it into artifacts, schemas, validators, stage transitions, persistence slices, and runtime behavior.
2. Every feature must map to an upstream input and downstream consumer.
3. Every persisted feature must point to a table, schema, or explicit artifact contract.
4. Every cutover feature needs a fixture or dry validation path before it can be considered done.
5. Keep optimization, calibration, and maturity work separate from the live-cutover path unless Section 18 marks it as a blocker.

## Downstream Tuning Persistence Spine

The v2 system must collect tuning material from the first fixture runs onward. This does not mean building full autonomous optimization before cutover; it means every live-cutover component writes enough structured, replayable data for later evaluation. The shared inventory tracks these as `MIG-001` to `MIG-013`.

| Migration Group | Owner | Required Write Path | Plain Purpose |
| --- | --- | --- | --- |
| `MIG-001` foundation/artifact manifest | Session 1 | `write_artifact_manifest()` | Store artifact schema, hash, timestamp, producer, and lineage so old forecasts can be replayed exactly. |
| `MIG-002` stage/status/execution/error records | Session 1 | `write_stage_status()`, `write_stage_execution_event()`, `write_pipeline_error_event()` | Store where each case is in the pipeline, every stage wrapper lifecycle event, safe log/artifact refs, replay commands, and why the case failed, blocked, retried, or downgraded. |
| `MIG-013` pipeline automation records | Session 1 | `write_pipeline_run()`, `write_pipeline_control_state()`, `acquire_case_lease()`, `write_pipeline_loop_iteration()`, `write_pipeline_stop_signal()`, `release_case_lease()` | Store durable enable/disable state, continuous run identity, selected case leases, stop/drain requests, loop iterations, retry/backoff state, terminal outcomes, and duplicate-prevention evidence. |
| `MIG-012` intake/case contract records | Session 2 | `write_case_intake_handoff()`, `write_ads_case_contract()` | Bind existing intake `markets`/`market_snapshots` rows, dispatch identity, source cutoff, raw payload hashes, and case contract artifact refs before evidence packet creation. |
| `MIG-003` decomposition/QDT records | Session 3 | `write_decomposition_run()`, `write_qdt_research_sufficiency_requirements()` | Store selected decomposition, leaves, branches, dependency groups, AMRG usage, canonical template/schema provenance, per-leaf research sufficiency requirements, and model provenance. |
| `MIG-004` retrieval/evidence records | Session 3 | `write_retrieval_packet()`, `write_retrieval_evidence_items()`, `write_retrieval_evidence_chunk_slices()`, `write_native_research_attempts()`, `write_browser_retrieval_attempts()`, `write_browser_search_provider_diagnostics()`, `write_source_metadata_classifier_slices()`, `write_source_metadata_resolution_slices()`, `write_atomic_claim_candidate_slices()`, `write_claim_family_resolution_slices()`, `write_metadata_fill_diagnostics()`, `write_retrieval_quality_slices()`, `write_evidence_provenance_slices()`, `write_retrieval_breadth_profile()`, `write_retrieval_breadth_coverage_slices()`, `write_contradiction_search_attempts()`, `write_negative_check_attempts()`, `write_source_access_and_missingness_slices()`, `write_retrieval_fallback_state()`, `write_retrieval_expansion_attempts()`, `write_research_sufficiency_certificate()` | Store approved retrieval transport provenance, OpenClaw browser/search provider diagnostics, browser capture provenance, optional GPT-native research provenance, optional small GPT classifier proposals/accepted assist decisions, admitted evidence items, bounded chunk/span refs, source metadata resolution decisions, atomic claim candidates, claim-family resolutions, fill-rate diagnostics, source, claim-family, source-family, source-class, temporal, breadth, contradiction, negative-check, retrieval-quality, missingness, fallback data, expansion attempts, and high-certainty sufficiency certificates. |
| `MIG-005` AMRG records | Session 2 | `write_related_market_context()` | Store candidates, edge types, timing validation, anchor eligibility, refresh events, and model-assist provenance. |
| `MIG-006` classification/verification records | Session 4 | `write_leaf_research_assignments()`, `write_researcher_context_isolation_audits()`, `write_researcher_classifications()`, `write_verification_slices()`, `write_researcher_coverage_proofs()`, `write_researcher_escalation_decisions()`, `write_research_sufficiency_reconciliation()` | Store compact per-leaf assignment packets, context-isolation audit records, leaf classifications, extracted values, quality dimensions, evidence-review coverage proofs, trigger-gated researcher escalation decisions, sufficiency reconciliation, side checks, verifier results, and model provenance. |
| `MIG-007` SCAE ledger records | Session 5 | `write_scae_ledger()`, `write_scae_research_sufficiency_inputs()` | Store priors, signed log-odds updates, caps, netting, cross-leaf dependence, branch sub-ledgers, research sufficiency intake, intervals, calibration context, and final probability fields. |
| `MIG-008` forecast/decision records | Session 5 | `write_forecast_decision()`, `record_market_prediction()`, `record_prediction_with_snapshot()` | Store only SCAE `production_forecast_prob`, forecast validity, actionability status, and a scoreable prediction-time market baseline bridge in existing `market_predictions`. |
| `MIG-009` training trace/replay records | Session 5 primary; Session 6 contributor for full trace materialization | `write_minimal_training_trace()`, `write_replay_manifest()`, `write_full_training_trace_materialization()` | Store hashes and pointers for the first 100+ runs and later full trace materialization without live authority. |
| `MIG-010` outcome/scoring records | Session 5 | `write_resolution_score()`, `settle_market_outcome()`, `brier_score_report()` | Store outcome, pipeline Brier, prediction-time market baseline Brier, Brier edge, reliability bucket, and resolution provenance from the existing scoring spine. |
| `MIG-011` calibration/tuning records | Session 6 | `write_calibration_candidate()`, `promote_policy_pointer()`, `write_policy_rollback_event()` | Store policy candidates, lane ownership, canary state, active pointers, rollback pointers, diagnostics, and promotion decisions. |

Write-path contract rules:

1. Each write path must be idempotent on a stable dispatch/run/artifact key.
2. Each record must include `case_id` or `case_key`, `dispatch_id` when applicable, produced timestamp, schema/policy version, artifact refs or source refs, and metadata for forward-compatible diagnostics.
3. Every live stage wrapper must write `v2_stage_execution_events` for `stage_started`, `stage_completed`, `stage_failed`, `stage_blocked`, `retry_scheduled`, and `artifact_validation_failed` as applicable. These events must include stage attempt ID, runner/component refs, command hash, bounded stdout/stderr/log artifact refs or an explicit no-log reason, safe exception summaries, retry metadata, resource counters when available, and a replay command.
4. Runtime integration cannot write tuning-critical facts only into untyped `details` blobs. Temporary bootstrap tables are acceptable for fixture work, but each cutover-critical surface needs a named table or explicit artifact schema before live cutover.
5. Tuning workers may read these records and write candidates, scorecards, and replay outputs. They must not write production forecasts or rewrite base policy files.
6. SCAE remains the only live numeric forecast authority; tuning records are non-authoritative until promoted through active policy pointers.
7. Decomposition, retrieval, researcher, and verifier artifacts must be schema-bound machine artifacts. Narrative explanations are optional debug attachments; SCAE consumes only validated structured fields and artifact refs.
8. Research sufficiency is an explicit write-path contract, not a soft prompt instruction. The live path cannot dispatch researcher classification for a leaf until retrieval has either produced a high-certainty sufficiency certificate or recorded a policy-valid structural unanswerability proof after exhausting bounded expansion.
9. Every SCAE production forecast must be written to the scoreable prediction bridge with the exact prediction-time market snapshot or a freshly recorded snapshot, so future Brier comparisons are against the market price available at forecast time, not a later price.

## Dependency Ladder

### Layer 0: Shared Foundations

These must be done first because every other session needs stable contracts.

- `FND-001`: canonical feature inventory and dependency DAG.
- `FND-002`: v2 stage vocabulary, status model, and stage execution event stream: `related_market_context`, `related_market_refresh`, `decomposition`, `retrieval`, `classification_verification`, `scae`, `synthesis`, `decision`.
- `FND-003`: artifact manifest model with generated timestamp, source cutoff, schema version, artifact path, SHA-256, and validation status.
- `FND-004`: Section 10 persistence migration plan and schema stubs, including `MIG-001` to `MIG-013` coverage.
- `FND-005`: golden fixture registry and fixture runner for a minimal binary market case.
- `FND-006`: fail-closed validation, safe stage execution logging, and pipeline error event conventions.
- `FND-007`: training trace minimal pointer contract, because the first 100 runs must be replayable.
- `AUTO-001`: continuous Orchestrator runner contract with run identity, mode, stop/drain controls, and stage order.
- `AUTO-002`: unique eligible-case selector and lease/idempotency guard over the existing case pipeline database.
- `AUTO-003`: end-to-end dispatch state machine from leased case to persisted SCAE forecast.
- `AUTO-004`: retry/backoff, soft-fail/quarantine, stop-after-current, drain, and stuck-lease recovery policy.
- `AUTO-005`: continuous loop fixture proving multiple unique cases run sequentially until stopped.
- `AUTO-006`: durable manual `pipeline_enabled` control switch checked before start/restart and before every new case lease.

### Layer 1: Pre-Decomposition Case Context

These unblock AMRG and decomposition.

- `CASE-001`: existing case pipeline adapter over SQLite `markets` and `market_snapshots`, including raw payload hashes and source row IDs.
- `CASE-002`: `ads-case-contract/v1` artifact with dispatch identity, snapshot/cutoff semantics, source-table refs, and downstream handoff slots.
- `CTX-001`: evidence packet v2 contract with family-aware binary child context, side mapping, source-of-truth status, market prior refs, and regime seed fields.
- `CTX-002`: market family metadata and sibling diagnostics.
- `CTX-003`: rolling market microstructure and prior-reliability input surfaces.
- `POL-001`: tunable registry metadata contract.
- `POL-002`: deterministic market-regime tags.
- `POL-003`: `effective_tuning_profile_context.json` resolver with `global_baseline_profile` default and conservative overlays only.
- `MODEL-001`: model lane policy artifact, `plans/autonomous-decomposition-swarm-model-lane-policy.json`, with `gpt-5.5-high` as the configured default for decomposer QDT generation, researcher leaf NLI classification, and native research candidate discovery, plus the OpenAI OAuth-routed `source_metadata_classifier_assist` lane defaulting to provider/model key `openai/gpt-5.4-mini`.

### Layer 2: AMRG

AMRG should be built in a weak-context-first path, then promoted effects later.

- `AMRG-001`: active-safe candidate pool construction.
- `AMRG-009`: local Ollama-routed `BAAI/bge-base-en-v1.5` vector index over active-safe market descriptors, emitting weak-context neighbor candidates and non-blocking unavailable diagnostics.
- `AMRG-002`: `related-live-market-context.json` schema and no-related-context waiver.
- `AMRG-003`: deterministic relationship typing and timing-alignment fields.
- `AMRG-004`: model-assist packet contract and schema-validated output, advisory only.
- `AMRG-005`: relationship slices, graph-safety slices, and refresh events.
- `AMRG-006`: refresh-first lifecycle with conservative downgrade on stale promoted effects.
- `AMRG-007`: shared retrieval/classification reuse cache, temporal eligibility only.
- `AMRG-008`: strict-precedence prior-anchor validation and audit records.

### Layer 3: Decomposition and Retrieval

These become the task contract for the swarm.

- `QDT-001`: decomposer invocation handoff using artifact paths and digests.
- `QDT-002`: `question-decomposition.json` schema with depth-2 tree, required leaves, branch IDs, information weights, dependency groups, and AMRG usage.
- `QDT-003`: deterministic structural validation, no LLM adversarial validator.
- `QDT-004`: AMRG anchor dependency contracts with optional, diagnostic, and repair-required policies.
- `QDT-005`: per-leaf high-certainty research sufficiency requirements embedded in the canonical QDT template, including required source classes, required values, negative checks, protected-primary rules, independent claim-family minimums, recency windows, expansion budget, and unanswerability proof rules.
- `MODEL-002`: decomposer QDT invocation resolves the `decomposer_qdt_generation` model lane and records `resolved_model_id`, `model_policy_ref`, `prompt_template_sha256`, and output schema version in the QDT artifact.
- `RET-001`: retrieval packet schema and per-leaf query construction.
- `RET-002`: strict temporal isolation validator.
- `RET-003`: retrieval quality scoring.
- `RET-004`: source, browser-capture, claim-family, source-family, independence, and temporal provenance. Browser browsing is a retrieval transport; the source remains the captured publisher/page/entity, not the agent browser. First cutover uses the OpenClaw `web_fetch` / browser provider, direct official/resolution URL capture first, and no news API dependency.
- `RET-005`: protected-primary access and missingness candidate tracking.
- `RET-006`: bounded starvation expansion and macro fallback.
- `RET-007`: local embedding/reranker preflight and resource caps.
- `RET-010`: optional GPT-5.5 native research candidate-discovery transport plus deterministic source metadata resolver. Native research may discover citations, snippets, candidate claims, and proposed labels, but final source-class/source-family/claim-family/temporal-safety fields are accepted only through resolver evidence and otherwise become `unknown_not_counted`. Native transport unavailability must be diagnostic, not blocking, when browser retrieval or another approved transport can satisfy sufficiency.
- `RET-011`: optional small GPT metadata/classifier/parser assist lane using OpenAI OAuth and `openai/gpt-5.4-mini` by default. It receives compact source-candidate packets and may provide accepted source-class values for non-protected sources, source-family/syndication hints, normalized claim tuple proposals, and visible-date candidates only when deterministic validators accept them. It cannot satisfy protected-primary/source-of-truth or temporal-safety requirements by itself, and classifier unavailability must not block non-critical retrieval.
- `RET-001` / `RET-004`: first-cutover retrieval is transport-abstract and may run browser-only through `openclaw_web_fetch_browser`. Direct official/resolution URLs from the case contract, market rules, protected-primary hints, or resolution source are captured before broad web search; OpenClaw browser/web-search expansion runs only when available and needed. The blocking core is admitted `retrieval-evidence/v1` items, bounded chunk/span refs, deterministic source metadata resolution, atomic claim candidate validation, claim-family resolution, temporal eligibility, breadth coverage, and sufficiency certification. News/feed API adapters are reserved future transports, not live-cutover prerequisites.
- `RET-009`: retrieval breadth profile and coverage validator. Each leaf receives explicit source-class, claim-family, source-family, freshness, contradiction-search, negative-check, and protected-primary requirements. Same-source-family or same-claim-family duplicates cannot satisfy independent breadth. Unknown source class/family does not satisfy a required breadth dimension.
- `RET-008`: high-certainty retrieval sufficiency loop and per-leaf sufficiency certificate. Thin retrieval must trigger bounded targeted expansion before classification; macro fallback is a marked last-resort input and cannot satisfy critical/source-of-truth leaves without structural unanswerability proof. Certification consumes `RET-009` breadth coverage instead of raw source counts.

### Layer 4: Researcher Classification and Verification

This replaces probability-authoring swarm output.

- `CLS-001`: researcher prompt contract with macro question, market reality constraints, required leaves, and retrieval evidence.
- `CLS-006`: compact `leaf-research-assignment/v1` artifact for each leaf researcher subagent. The assignment packet uses artifact refs, evidence refs, sufficiency certificate refs, hashes, enums, and budget/deadline caps instead of duplicated evidence bodies or narrative instructions.
- `CLS-008`: researcher subagent context isolation. Each leaf researcher launches in a fresh context that contains only its own assignment packet, allowed evidence refs/snippets, prompt/schema refs, and model context. It must not receive sibling assignments, peer outputs, aggregate conclusions, SCAE refs, replay/scoring outcomes, or prior researcher sidecars.
- `CLS-002`: sidecar schema rejects researcher probabilities, fair values, intervals, and reassembly fields.
- `CLS-003`: NLI evidence classification matrix with direction, strength, confidence, quality dimensions, and condition scope.
- `CLS-004`: supplemental evidence normalization boundary.
- `CLS-005`: researcher evidence-review coverage proof against each leaf's sufficiency requirements and assigned evidence refs.
- `CLS-007`: adaptive researcher escalation decision contract. Default is one primary researcher per leaf; extra assignments are generated only when a machine-readable trigger fires: critical/source-of-truth leaf, evidence conflict, low retrieval confidence, low classification confidence, high pre-SCAE leverage proxy, or structural unanswerability claim. Escalation decisions are bounded, persisted, and cannot author probabilities.
- `MODEL-003`: researcher leaf NLI classification resolves the `researcher_leaf_nli_classification` model lane and records `resolved_model_id`, `model_policy_ref`, `prompt_template_sha256`, sidecar schema version, and classification output schema version.
- `VER-001`: direction verification slices for all non-neutral classifications.
- `VER-002`: evidence-quality verification slices and accepted multiplier fields.
- `VER-003`: completion reconciliation requires classification coverage and SCAE-readiness.
- `VER-004`: research sufficiency reconciliation proves every SCAE-bound leaf has high-certainty coverage, verified structural unanswerability, or an explicit non-live blocker after required researcher escalations are complete; it must not turn thin retrieval into a normal SCAE-ready input.

### Layer 5: SCAE, Synthesis, Decision

This is the v2 live forecast path.

- `SCAE-001`: base SCAE policy and probability field taxonomy.
- `SCAE-002`: prior odds, prior reliability, structural/base-rate shrinkage, and market-assimilation context.
- `SCAE-003`: evidence delta mapping with direction, quality, retrieval, temporal, and policy modifiers.
- `SCAE-004`: correlated-quality guard and cap stack.
- `SCAE-005`: intra-leaf representative cluster netting.
- `SCAE-006`: cross-leaf dependence guard and shared-claim union.
- `SCAE-007`: branch sub-ledgers with sign-partitioned covariance penalties.
- `SCAE-008`: missingness and survival/no-catalyst policy.
- `SCAE-009`: family-aware binary child diagnostics and displacement signals.
- `SCAE-010`: AMRG conditional branch recombination for validated strict-precedence anchors only.
- `SCAE-011`: deterministic logit interval builder.
- `SCAE-012`: identity-by-default post-ledger calibration and calibration-debt controls.
- `SCAE-013`: SCAE research sufficiency intake. The ledger records sufficiency certificate refs, rejects missing high-certainty readiness for live-valid forecasts, and includes residual sufficiency gaps only as invalid/watch-only diagnostics, never as clean evidence.
- `SYN-001`: synthesis consumes SCAE and annotates qualitative leverage only.
- `DEC-001`: Decision/Execution Gate consumes `production_forecast_prob` and may downgrade execution only.
- `PERSIST-001`: production forecast persistence writes only SCAE `production_forecast_prob`.
- `PERSIST-002`: existing scoring bridge writes the SCAE forecast into `market_predictions` with `market_snapshot_id`, `market_probability`, snapshot age, artifact hashes, `prediction_run_id`, `forecast_artifact_id`, `case_key`, `case_id`, and `dispatch_id`.

### Layer 6: Replay, Calibration, and Maturity

This should not block initial v2 cutover except for minimal trace capture and replayability.

- `TRACE-001`: synchronous `training_trace_minimal` pointer.
- `MODEL-004`: training/replay trace records resolved model IDs, model policy refs, prompt/template hashes, input/output artifact hashes, and schema versions for decomposer and researcher model calls.
- `TRACE-002`: async full trace materialization owned by Session 6 after minimal trace and replay records exist.
- `REPLAY-001`: first-100 direct-cutover replay manifests and result records.
- `SCORE-001`: Brier and market-baseline scoring through existing `settle_market_outcome()` / `brier_score_report()` surfaces.
- `CAL-001`: calibration-debt context and explicit clearance gates.
- `CAL-002`: lane definitions, candidate queues, active pointers, canaries, rollback events, and lane health, owned by Session 6.
- `CAL-003`: retrieval-policy calibration snapshots, owned by Session 6.
- `CAL-004`: decomposer-profile and decision/actionability-profile lanes, owned by Session 6.
- `CAL-005`: autonomous optimization maturity gates, owned by Session 6.

## Six Concurrent Development Sessions

### Session 1: Foundation, Contracts, and Control Plane

Owns the surfaces that every other session imports.

Initial tasks:

- Maintain the human-readable inventory and the machine-readable `plans/autonomous-decomposition-swarm-feature-inventory.yaml`.
- Maintain the dependency gate command `python3 plans/check_dependency_gates.py`.
- Maintain the live-cutover blocker matrix, schema-name map, and golden fixture matrix.
- Add v2 stage vocabulary, status snapshot, and stage execution event contracts.
- Add artifact manifest, validation, stage execution event, error event, replay, and golden fixture schema stubs.
- Add continuous automation runner, case lease, loop iteration, and stop/drain record contracts.
- Expand the foundation migration plan from generic `details` tables into named v2 persistence surfaces or explicit JSON artifact contracts.
- Own `MIG-001`, `MIG-002`, and `MIG-013`, and keep the shared `MIG-001` to `MIG-013` coverage matrix in sync as other sessions add write paths.
- Create the fixture runner shape for one minimal binary market.

First integration output:

- A minimal end-to-end fixture can register stage statuses, write stage execution events with safe log refs and replay commands, write artifact manifests, validate schemas, record automation loop state, and fail closed without running AMRG, retrieval, or SCAE.

### Session 2: Evidence Packet, Policy Context, and AMRG

Owns pre-decomposition market context and related live-market context.

Initial tasks:

- Implement the ADS case contract passover from existing SQLite intake rows before evidence packet creation.
- Extend evidence packet v2 contract.
- Materialize family-aware binary child metadata and prior-reliability inputs.
- Implement market-regime tag and tuning-profile context stubs.
- Implement local AMRG vectorization with the `amrg_vector_embedding` policy lane, Ollama route, `BAAI/bge-base-en-v1.5` download/wiring contract, active-safe descriptor hashing, vector index snapshots, neighbor candidate rows, and non-blocking unavailable diagnostics.
- Implement AMRG no-related-context waiver, candidate construction, timing fields, and weak-context artifact first.
- Add AMRG refresh event and conservative downgrade contracts.
- Own `MIG-005` AMRG records and contribute CTX/POL persistence fields to `MIG-001` and `MIG-002` manifests/statuses through Session 1's contract.

First integration output:

- Given an existing intake market/snapshot fixture, produce a valid `ads-case-contract/v1`, evidence packet, regime/profile context, optional local-vector candidate diagnostics, and either a valid weak-context AMRG artifact or an explicit no-related-context waiver. Ollama/BGE unavailability must be recorded without blocking this output.

### Session 3: Decomposer and Retrieval Packet

Owns the canonical task contract and evidence acquisition packet.

Initial tasks:

- Implement decomposer artifact schema, handoff contract, and structural validator.
- Build deterministic leaf/question validation with required-purpose coverage and required research sufficiency fields.
- Add AMRG usage recording and anchor dependency contract fields.
- Implement retrieval packet schema, browser-first retrieval transport, optional GPT-5.5 native research candidate discovery, optional OpenAI OAuth-routed `gpt-5.4-mini` source metadata/claim parser classifier-assist slices, admitted evidence items, bounded chunk/span refs, source metadata resolver slices, atomic claim candidate validation, claim-family resolution slices, temporal isolation validation, retrieval quality slices, source/claim-family/source-family provenance, retrieval breadth profiles, contradiction and negative-check attempts, targeted expansion attempts, high-certainty sufficiency certificates, and macro fallback states.
- Add local model preflight contracts before real embedding/reranking integration.
- Own `MIG-003` decomposition/QDT records and `MIG-004` retrieval/evidence records.

First integration output:

- Given Session 2 artifacts, produce a valid `question-decomposition.json` and a valid `retrieval-packet.json` using fixture or stub retrieval evidence, with per-leaf research sufficiency requirements, retrieval breadth profiles, breadth coverage slices, and certificates.

### Session 4: Researcher Classification and Verification

Owns the replacement of probability-output swarm artifacts.

Initial tasks:

- Rewrite researcher prompt contract into NLI classification tasks.
- Define and validate compact `leaf-research-assignment/v1` packets before spawning leaf researcher subagents.
- Validate per-subagent context isolation before spawn and write isolation audit records.
- Add v2 sidecar schema and no-probability validation.
- Implement classification matrix rendering and completion checks.
- Implement researcher coverage proofs that show every required evidence ref and sufficiency requirement was reviewed or explicitly unanswerable.
- Implement `researcher-escalation-decision/v1`: one primary researcher per leaf by default, bounded extra assignments only for configured escalation triggers, and no probability-bearing escalation logic.
- Implement supplemental evidence normalization.
- Implement direction verification, evidence-quality verification, and high-certainty sufficiency reconciliation slices.
- Own `MIG-006` classification/verification records.

First integration output:

- Given Session 3 retrieval packets, produce compact isolated leaf assignment fixtures and researcher sidecar fixtures that pass no-probability validation, prove evidence-review coverage, resolve required adaptive researcher escalations, and materialize high-certainty SCAE-ready verified classification slices.

### Session 5: SCAE, Synthesis/Decision Handoff, and Evaluator Spine

Owns the numeric authority and non-authoritative learning traces.

Initial tasks:

- Implement SCAE policy, probability field taxonomy, and ledger artifact skeleton.
- Build prior reliability, evidence delta, cap stack, cluster netting, cross-leaf dependence, branch sub-ledger, research sufficiency intake, interval, and calibration-debt modules incrementally.
- Gate synthesis so it cannot author probability ranges.
- Gate decision so it persists only SCAE `production_forecast_prob`.
- Bridge forecast persistence into existing `market_predictions` with prediction-time market snapshot provenance and Brier baseline fields.
- Add minimal training trace, replay manifest, and calibration-debt context.
- Own `MIG-007` SCAE ledger records, `MIG-008` forecast/decision records, `MIG-009` minimal trace/replay records, and `MIG-010` outcome/scoring records.
- Hand maturity calibration lanes and `MIG-011` to Session 6 once `TRACE-001`, `REPLAY-001`, `CAL-001`, and `POL-001` are available.

First integration output:

- Given Session 4 verified classification slices and sufficiency reconciliation, produce an auditable SCAE ledger with `raw_ledger_probability`, `post_ledger_probability`, `debt_adjusted_probability`, `production_forecast_prob`, research sufficiency context, a decision context that cannot override it, and a scoreable `market_predictions` row tied to the prediction-time market snapshot.

### Session 6: Evaluator/Tuning Agent and Optimization Maturity

Owns autonomous optimization maturity after the live path is replayable and calibration debt gates exist.

Initial tasks:

- Implement async full trace materialization as a non-authoritative extension of `MIG-009`.
- Build calibration lane storage, candidate queues, active pointers, canary state, rollback events, and lane health under `MIG-011`.
- Build component diagnostics and protected-slice non-degradation checks for post-ledger calibration candidates.
- Build retrieval-policy calibration snapshots from replay/scoring records.
- Build decomposer-profile and decision/actionability profile calibration lanes.
- Define autonomous optimization maturity gates and emergency conservative overlay semantics.
- Never write production forecasts, rewrite base policy files, or select live numeric weights outside promoted active pointers.

First integration output:

- Given Session 5 replay and scoring records, produce a non-authoritative calibration candidate with component diagnostics, canary status, rollback pointer, and no ability to alter live forecasts until explicitly promoted through policy pointers.

## Sequencing Across Sessions

Use three waves so work can run concurrently without violating dependency order.

### Wave A: Contract Freeze

Session 1 produces schema stubs, artifact conventions, stage names, fixture harness, machine-readable inventory, dependency gate command, blocker matrix, schema-name map, and fixture matrix. Sessions 2-6 use those contracts immediately with fixture data.

Exit gate:

- Every planned v2 artifact has a path, schema name, owner, upstream inputs, downstream consumers, and persistence surface.
- Every migration group `MIG-001` to `MIG-013` has an owner, write path contract, and table/schema/artifact destination.
- `python3 plans/check_dependency_gates.py` validates the machine-readable inventory, rejects missing dependencies, rejects cycles, and blocks runtime integration unless upstream rows are ready or explicitly waived. Use `--report-only` for readiness briefs that need blocker context without treating expected `BLOCKED` rows as shell failures.
- The live-cutover blocker matrix, schema-name map, and golden fixture matrix have owner/status coverage for all cutover-critical rows.

### Wave B: Fixture-First Vertical Slice

Each session implements its own component against fixtures, not live runtime. Session 6 may build maturity fixtures, but its outputs remain non-authoritative and cannot be required for v2 live cutover.

Exit gate:

- One fixture case can flow from existing intake `markets` / `market_snapshots` rows through `ads-case-contract/v1`, evidence packet, AMRG waiver, decomposition, retrieval packet, compact leaf-research assignments, classification sidecars, verification, SCAE ledger, synthesis annotation, decision context, and scoreable prediction persistence without live execution.
- A two-case fixture proves the automation runner selects a unique eligible case, runs it through the vertical slice, releases its lease, selects a second unique case, and stops cleanly on a stop-after-current signal.
- The fixture path proves at least one initially thin leaf receives bounded targeted expansion until it earns a high-certainty sufficiency certificate before researcher classification; a deliberately impossible leaf must produce structural unanswerability proof instead of a clean SCAE-ready row.

### Wave C: Runtime Integration

Wire validated components into the real case progression path in dependency order.

Required order:

1. Stage/status/execution-event/control-plane visibility.
2. Automation runner, stop/drain contract, and case lease records.
3. Existing intake market/snapshot passover into `ads-case-contract/v1`.
4. Evidence packet and profile context.
5. AMRG attempt or waiver.
6. Decomposition.
7. Retrieval with high-certainty sufficiency certification.
8. Researcher classification dispatch only after sufficiency certificates or structural unanswerability proofs exist.
9. Verification, sufficiency reconciliation, and SCAE ledger.
10. Synthesis annotation.
11. Decision/Execution Gate.
12. Forecast persistence to decision records and existing `market_predictions` with prediction-time market snapshot provenance.
13. Decomposer/researcher model provenance from the configured `gpt-5.5-high` lanes.
14. Minimal trace and replay records.
15. Resolution/scoring writes use existing settlement and Brier reporting paths; scoring records remain non-authoritative but are schema-valid before calibration debt clearance work begins.
16. Calibration candidate write paths are Session 6 maturity work and remain non-authoritative until promoted through policy pointers.

Exit gate:

- v2 live cutover checklist in Section 18.1 is green for a fixture, then a non-executing canary, then a direct production run under `calibration_debt_mode`.

## Implementation Guardrails

- Do not create a second live forecast authority.
- Do not let Decision-Maker or synthesis persist replacement probabilities.
- Do not let AMRG write SCAE evidence deltas.
- Do not let thin retrieval proceed as normal research. The system must exhaust the configured targeted expansion loop before classification, and any remaining gap must be represented as structural unanswerability or an invalid/watch-only forecast state, not as ordinary low-confidence evidence.
- Do not use model-only AMRG edges for promoted effects.
- Do not build full autonomous calibration before the v2 live path is contract-valid.
- Do not promote non-identity post-ledger calibration or loosen caps until replay gates clear.
- Do not treat grouped Polymarket children as context-free binaries when family metadata exists.
- Do not implement sibling softmax or joint categorical forecasting during initial cutover.

## Immediate Next Planning Step

Before launching workers, run `python3 plans/check_dependency_gates.py --all --mode runtime_integration --report-only`, reconcile any `unresolved` or `needs_new_migration` rows in the schema-name map, and keep the Markdown inventory, machine-readable inventory, coverage map, blocker matrix, fixture matrix, and session plans in sync. Spawn ADS worker sessions with cwd set to `/Users/agent2/.openclaw/orchestrator`; worker prompts should tell sessions to use `python3`, verify paths with `rg --files` before opening guessed files, and append `--report-only` when collecting blocker context. After that, start all sessions in fixture mode; runtime integration waits for dependency gates to turn green.
