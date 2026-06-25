# Autonomous Decomposition-Swarm Script Placement Map

Purpose: prevent runtime code from scattering across `.openclaw`. Every new ADS script must be filed under the runtime owner that actually performs the work.

## Runtime Owners

| Owner | Workspace | Script root | Responsibility |
| --- | --- | --- | --- |
| Orchestrator | `/Users/agent2/.openclaw/orchestrator` | `/Users/agent2/.openclaw/orchestrator/scripts` | Case intake, stage/status, artifact manifests, wakeups, handoffs, AMRG/evidence context, synthesis/decision routing, post-SCAE operations, evaluation orchestration. |
| ADS Decomposer | `/Users/agent2/.openclaw/decomposer` | `/Users/agent2/.openclaw/decomposer/scripts` | QDT generation, QDT validation, decomposition repair/fallback, leaf research sufficiency requirement construction. |
| ADS Researcher Swarm | `/Users/agent2/.openclaw/researcher-swarm` | `/Users/agent2/.openclaw/researcher-swarm/scripts` | Retrieval, retrieval expansion, researcher subagent coordination, leaf research, NLI classification sidecars, coverage proofs, verification, sufficiency reconciliation. |
| SCAE | `/Users/agent2/.openclaw/SCAE` | `/Users/agent2/.openclaw/SCAE/scripts` | Deterministic ledger math, cap stack, netting, interval builder, debt controls, scoreable SCAE forecast persistence helpers. |

## Folder Shape

Every script root follows the Orchestrator script bundle shape:

```text
scripts/
  bin/
  <importable_package>/
  migrations/
  tests/
  data/
  .runtime-state/
  requirements.txt
  README.md
```

Root-level runtime entrypoints should be avoided except for compatibility shims explicitly documented in that script root's README.

## Planned Script Paths

### Orchestrator Scripts

| Planned path | Owning features | Purpose |
| --- | --- | --- |
| `/Users/agent2/.openclaw/orchestrator/scripts/bin/build_ads_case_contract.py` | `CASE-001`, `CASE-002`, `MIG-012` | Build the ADS case contract from existing `markets` / `market_snapshots` rows. |
| `/Users/agent2/.openclaw/orchestrator/scripts/predquant/ads_case_contract.py` | `CASE-001`, `CASE-002`, `MIG-012` | Importable case-contract builder, validator, and source provenance helpers. |
| `/Users/agent2/.openclaw/orchestrator/scripts/bin/build_evidence_packet_v2.py` | `CTX-001`, `CTX-002`, `CTX-003` | Materialize the evidence packet from the ADS case contract. |
| `/Users/agent2/.openclaw/orchestrator/scripts/predquant/evidence_packet.py` | `CTX-001`, `CTX-002`, `CTX-003` | Evidence packet schema, validation, family context, and prior-reliability inputs. |
| `/Users/agent2/.openclaw/orchestrator/scripts/bin/resolve_tuning_profile_context.py` | `POL-001`, `POL-002`, `POL-003` | Resolve deterministic regime/profile context. |
| `/Users/agent2/.openclaw/orchestrator/scripts/predquant/tuning_profile.py` | `POL-001`, `POL-002`, `POL-003` | Importable tuning profile policy helpers. |
| `/Users/agent2/.openclaw/orchestrator/scripts/bin/build_related_live_market_context.py` | `AMRG-001` to `AMRG-009`, `MIG-005` | Build AMRG artifact or waiver, including local vector candidate source diagnostics. |
| `/Users/agent2/.openclaw/orchestrator/scripts/predquant/amrg.py` | `AMRG-001` to `AMRG-009`, `MIG-005` | Importable AMRG candidate, vector, timing, and refresh helpers. |
| `/Users/agent2/.openclaw/orchestrator/scripts/bin/run_ads_pipeline_loop.py` | `AUTO-001` to `AUTO-005`, `MIG-013` | Continuous Orchestrator-owned runner that leases one eligible case, drives all stages, persists SCAE forecast, then selects the next case until stopped. |
| `/Users/agent2/.openclaw/orchestrator/scripts/bin/set_ads_pipeline_enabled.py` | `AUTO-006`, `MIG-013` | Manually enable or disable the durable ADS pipeline control switch. |
| `/Users/agent2/.openclaw/orchestrator/scripts/bin/get_ads_pipeline_control.py` | `AUTO-006`, `MIG-013` | Inspect current durable ADS pipeline enablement and stop/drain state. |
| `/Users/agent2/.openclaw/orchestrator/scripts/bin/stop_ads_pipeline_loop.py` | `AUTO-004`, `MIG-013` | Write a stop/drain request for the continuous runner. |
| `/Users/agent2/.openclaw/orchestrator/scripts/predquant/ads_pipeline_control.py` | `AUTO-006`, `MIG-013` | Importable durable control-state helpers for `pipeline_enabled`, operator reason, and acknowledgement. |
| `/Users/agent2/.openclaw/orchestrator/scripts/predquant/ads_pipeline_runner.py` | `AUTO-001`, `AUTO-003`, `AUTO-004`, `AUTO-006`, `MIG-013` | Importable runner state machine, retry/backoff policy, enablement gate, stop/drain handling, and loop iteration records. |
| `/Users/agent2/.openclaw/orchestrator/scripts/predquant/ads_case_selector.py` | `AUTO-002`, `CASE-001`, `MIG-013` | Eligible-case selection, lease acquisition, idempotency, and stuck-lease recovery helpers. |
| `/Users/agent2/.openclaw/orchestrator/scripts/predquant/ads_stage_logging.py` | `FND-002`, `FND-006`, `MIG-002`, `AUTO-003`, `AUTO-004` | Importable stage wrapper logging helpers for `v2_stage_execution_events`, safe log artifact refs, retry/error links, stage status updates, and replay commands. |
| `/Users/agent2/.openclaw/orchestrator/scripts/bin/wake_decomposer.py` | `QDT-001`, `MODEL-002` | Orchestrator-owned wakeup/handoff to ADS Decomposer. |
| `/Users/agent2/.openclaw/orchestrator/scripts/bin/wake_researcher_swarm.py` | `CLS-001`, `MODEL-003` | Orchestrator-owned wakeup/handoff to ADS Researcher Swarm. |
| `/Users/agent2/.openclaw/orchestrator/scripts/bin/kick_scae.py` | `SCAE-001` to `SCAE-013` | Orchestrator-owned post-research SCAE invocation. |
| `/Users/agent2/.openclaw/orchestrator/scripts/predquant/ads_handoff.py` | `FND-002`, `FND-003`, handoff rows | Shared stage handoff validation and artifact-ref packing. |
| `/Users/agent2/.openclaw/orchestrator/scripts/bin/check_ads_script_placement.py` | `FND-001`, `FND-005`, `FIX-039`, `BLK-032` | Static scan that enforces this placement map before implementation/runtime integration. |
| `/Users/agent2/.openclaw/orchestrator/scripts/bin/run_golden_fixture.py` | `FND-005`, `FND-006`, `FIX-001` to `FIX-007`, `BLK-012` | Run the Orchestrator-owned golden fixture registry/result harness in fixture or runtime-dependency-check mode. |
| `/Users/agent2/.openclaw/orchestrator/scripts/predquant/golden_fixtures.py` | `FND-005`, `FND-006`, `FIX-001` to `FIX-007`, `BLK-012` | Importable golden fixture matrix parser, registry writer, starter fixture specs, result writer, and fail-closed validation/error-event harness. |
| `/Users/agent2/.openclaw/orchestrator/scripts/predquant/training_trace.py` | `FND-007`, `TRACE-001`, `MIG-009` | Importable minimal training trace pointer builder, validator, and persistence helper; records replayable artifact pointers and hashes without live forecast authority. |
| `/Users/agent2/.openclaw/orchestrator/scripts/bin/run_synthesis_annotation.py` | `SYN-001` | Run qualitative synthesis annotation after SCAE. |
| `/Users/agent2/.openclaw/orchestrator/scripts/bin/run_decision_gate.py` | `DEC-001`, `PERSIST-001` | Run decision/actionability gate after SCAE. |

### Decomposer Scripts

| Planned path | Owning features | Purpose |
| --- | --- | --- |
| `/Users/agent2/.openclaw/decomposer/scripts/bin/run_decomposition.py` | `QDT-001`, `QDT-002`, `MODEL-002` | Run QDT generation from Orchestrator handoff artifacts. |
| `/Users/agent2/.openclaw/decomposer/scripts/bin/validate_question_decomposition.py` | `QDT-002`, `QDT-003` | Validate `question-decomposition.json` against schema and deterministic structural rules. |
| `/Users/agent2/.openclaw/decomposer/scripts/bin/repair_anchor_dependency.py` | `QDT-004` | Apply bounded AMRG anchor dependency repair/fallback policy. |
| `/Users/agent2/.openclaw/decomposer/scripts/ads_decomposer/qdt.py` | `QDT-002`, `QDT-003`, `QDT-005` | QDT schema and construction helpers. |
| `/Users/agent2/.openclaw/decomposer/scripts/ads_decomposer/handoff.py` | `QDT-001` | Handoff parser and artifact manifest checks. |
| `/Users/agent2/.openclaw/decomposer/scripts/ads_decomposer/sufficiency_requirements.py` | `QDT-005` | Per-leaf research sufficiency requirement builder. |

### Researcher Swarm Scripts

| Planned path | Owning features | Purpose |
| --- | --- | --- |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/bin/run_researcher_swarm.py` | `CLS-001`, `CLS-006`, `CLS-008`, `CLS-005`, `CLS-007`, `MODEL-003` | Run the researcher-swarm stage for a validated QDT. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/bin/build_leaf_research_assignments.py` | `CLS-006`, `MODEL-003` | Build compact `leaf-research-assignment/v1` packets for leaf researcher subagents. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/bin/validate_researcher_context_isolation.py` | `CLS-008` | Validate per-subagent context allowlists/denylists and write context-isolation audit records before launch. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/bin/evaluate_researcher_escalations.py` | `CLS-007`, `VER-004` | Evaluate trigger-gated extra leaf-research assignments and write compact escalation decisions. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/bin/spawn_leaf_researchers.py` | `CLS-001`, `CLS-008`, `CLS-007`, `MODEL-003` | Create bounded isolated leaf researcher subagents. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/bin/build_retrieval_packet.py` | `RET-001` to `RET-011`, `MIG-004` | Build retrieval packet and sufficiency certificates for QDT leaves. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/bin/run_native_gpt_research.py` | `RET-010`, `RET-001`, `RET-004`, `RET-009`, `MIG-004` | Invoke GPT-5.5 native research/browsing for candidate discovery and write compact native research attempt records. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/bin/run_browser_retrieval.py` | `RET-001`, `RET-004`, `RET-009`, `MIG-004` | Execute OpenClaw `web_fetch` / browser retrieval: direct official/resolution URL capture first, then bounded web-search/site-search/followed-link expansion, and write compact browser retrieval attempt records. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/bin/run_source_metadata_classifier.py` | `RET-011`, `RET-004`, `RET-010`, `RET-009`, `MIG-004` | Invoke the OpenAI OAuth-routed `openai/gpt-5.4-mini` metadata classifier over compact source-candidate packets and write classifier-assist slices. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/bin/build_retrieval_breadth_profile.py` | `RET-009`, `MIG-004` | Build compact `retrieval-breadth-profile/v1` rows from QDT sufficiency requirements and profile context. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/bin/run_retrieval_expansion.py` | `RET-006`, `RET-008` | Run targeted expansion before classification when sufficiency is not met. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/bin/validate_retrieval_breadth.py` | `RET-004`, `RET-009`, `RET-008` | Validate source-class, claim-family, source-family, freshness, contradiction, negative-check, and protected-primary breadth before certification. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/bin/validate_researcher_sidecars.py` | `CLS-002`, `CLS-003`, `CLS-005` | Validate no-probability sidecars and evidence coverage proofs. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/bin/verify_evidence_directionality.py` | `VER-001` | Verify impact direction against side mapping and constraints. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/bin/verify_evidence_quality.py` | `VER-002` | Verify evidence quality fields and multiplier inputs. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/bin/reconcile_research_sufficiency.py` | `VER-003`, `VER-004` | Produce SCAE-ready, watch-only, or invalid sufficiency reconciliation. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/retrieval.py` | `RET-001` to `RET-011` | Importable retrieval and expansion helpers. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/native_research.py` | `RET-010` | Importable GPT-5.5 native research transport, citation candidate schema, model provenance, and forbidden-output checks. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/browser_provider.py` | `RET-001`, `RET-004`, `RET-009`, `MIG-004` | Importable OpenClaw browser provider resolver for `openclaw_web_fetch_browser`, capability checks, direct URL priority, `web_fetch`/browser refs, and provider diagnostics. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/browser_capture.py` | `RET-004`, `RET-009` | Importable browser capture normalization, canonical URL extraction, timestamp extraction, content hashing, and evidence candidate materialization helpers. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/metadata_classifier.py` | `RET-011` | Importable compact classifier packet builder, model-lane invocation, output schema validation, and acceptance/rejection diagnostics. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/metadata_resolver.py` | `RET-004`, `RET-010`, `RET-011`, `RET-009` | Importable layered resolver for source class, source family, claim family, temporal safety, metadata confidence, classifier acceptance status, and unknown diagnostics. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/evidence.py` | `RET-001`, `RET-002`, `RET-004`, `MIG-004` | Importable `retrieval-evidence/v1` and chunk/span schema helpers, admission status, content hashing, and artifact-ref validation. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/claim_extraction.py` | `RET-004`, `RET-011`, `RET-009`, `MIG-004` | Importable atomic-claim candidate validation, model/parser proposal acceptance, tuple normalization, claim-family hashing, equivalence, and contradiction-family helpers. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/source_registry.py` | `RET-004`, `RET-010` | Small curated registry and market-contract resolver for official/rules/common publisher/family matching. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/breadth.py` | `RET-004`, `RET-009` | Importable source-class, claim-family, source-family, contradiction, negative-check, and breadth coverage helpers. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/assignments.py` | `CLS-006` | Importable leaf assignment schema, builder, and compactness validator. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/isolation.py` | `CLS-008` | Importable context isolation policy, allowlist/denylist scans, and audit helpers. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/escalation.py` | `CLS-007` | Importable adaptive escalation policy, caps, pre-SCAE leverage proxy, and decision artifact helpers. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/classification.py` | `CLS-001` to `CLS-005` | Importable classification sidecar and coverage proof helpers. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/verification.py` | `VER-001` to `VER-004` | Importable verification and sufficiency reconciliation helpers. |
| `/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/subagents.py` | `CLS-001`, `MODEL-003` | Leaf researcher subagent coordination helpers. |

### SCAE Scripts

| Planned path | Owning features | Purpose |
| --- | --- | --- |
| `/Users/agent2/.openclaw/SCAE/scripts/bin/run_scae_ledger.py` | `SCAE-001` to `SCAE-013`, `MIG-007` | Build deterministic SCAE ledger from verified research artifacts. |
| `/Users/agent2/.openclaw/SCAE/scripts/bin/validate_scae_ledger.py` | `SCAE-001`, `SCAE-011`, `SCAE-012` | Validate ledger schema, probability taxonomy, interval, and authority boundaries. |
| `/Users/agent2/.openclaw/SCAE/scripts/bin/persist_scae_forecast.py` | `PERSIST-001`, `PERSIST-002`, `MIG-008` | Persist SCAE production probability and scoreable market prediction bridge. |
| `/Users/agent2/.openclaw/SCAE/scripts/bin/report_scae_scorecard.py` | `SCORE-001`, `MIG-010` | Summarize SCAE Brier and market-baseline scorecards. |
| `/Users/agent2/.openclaw/SCAE/scripts/scae/ledger.py` | `SCAE-001` to `SCAE-013` | Ledger construction and probability field contract. |
| `/Users/agent2/.openclaw/SCAE/scripts/scae/policy.py` | `SCAE-001`, `SCAE-004`, `SCAE-012` | SCAE policy resolution, caps, and debt controls. |
| `/Users/agent2/.openclaw/SCAE/scripts/scae/prior.py` | `SCAE-002` | Prior odds, rolling microstructure reliability, structural/neutral shrink targets, and market-assimilation context. |
| `/Users/agent2/.openclaw/SCAE/scripts/scae/family.py` | `SCAE-009` | Family-aware binary child displacement and consistency diagnostics with sibling prices as context only. |
| `/Users/agent2/.openclaw/SCAE/scripts/scae/netting.py` | `SCAE-005`, `SCAE-006`, `SCAE-007` | Intra-leaf, cross-leaf, branch, and dependence netting. |
| `/Users/agent2/.openclaw/SCAE/scripts/scae/intervals.py` | `SCAE-011` | Deterministic logit uncertainty interval builder. |
| `/Users/agent2/.openclaw/SCAE/scripts/scae/persistence.py` | `PERSIST-001`, `PERSIST-002`, `SCORE-001` | Forecast and scoring persistence helpers. |

## Enforcement Rules

1. Orchestrator may wake agents and pass artifacts, but should not contain decomposer-owned QDT generation code or researcher-owned leaf research code.
2. Decomposer scripts may not spawn researcher subagents or calculate probabilities.
3. Researcher-swarm scripts may not generate QDT structure or calculate probabilities.
4. SCAE scripts may not call live LLMs, conduct research, or create a second forecast authority.
5. If a planned script does not appear in this map, add it here before implementation begins.
