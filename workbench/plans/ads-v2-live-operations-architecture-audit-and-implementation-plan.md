# ADS v2 Live Operations Architecture Audit And Implementation Plan

Date: 2026-06-26; refreshed 2026-06-27
Author: Workbench
Scope: Development plan for fixing ADS v2 live-operation readiness while reusing the current Orchestrator, Decomposer, Researcher Swarm, AMRG, and SCAE architecture.

## Executive Summary

The ADS v2 pipeline architecture is now materially beyond the earlier pilot-only state. The control plane, manifests, leases, stage logging, readiness gates, canary harnesses, bounded scheduler, storage maintenance, scoring/calibration reporting, AMRG contract layer, and SCAE deterministic engine are present and tested. Current working-tree code also includes the true-production handler factory, Decomposer model-runtime transport, AMRG live vector runtime path, Researcher Swarm OpenClaw runtime adapter, stricter leaf-research barriers, and real-runtime canary reporting.

The remaining live-readiness gap is not the execution skeleton. It is the end-to-end live evidence path. A bounded true-production clone canary can now execute the Decomposer runtime path and complete all stages non-scoreably, but the live retrieval stage currently supplies no fetched, searched, or native candidate URLs into the retrieval materializer. That produces a certified retrieval blocker, prevents real Researcher Swarm execution, and leaves SCAE without verified classification-derived evidence deltas.

The fix should continue to modify the existing architecture, not create a parallel pipeline. The current runner, manifests, handler boundary, and SCAE authority model should remain the execution spine. The deterministic pilot lane should remain available as a fixture/canary lane, but true production readiness must require source-populated retrieval sufficiency, real Researcher model execution, verified sidecars, and SCAE evidence deltas derived from those verified artifacts.

## Audit Basis

Repo state checked from `/Users/agent2/.openclaw`:

- `main...origin/main` is not ahead/behind in the current workspace, with ADS runtime integration edits still present in the working tree. Treat those working-tree changes as current audit state until they are reconciled and pushed.
- Focused verification:
  - Orchestrator tests: 217 passing.
  - Decomposer tests: 64 passing.
  - Researcher Swarm tests: 169 passing.
  - SCAE tests: 104 passing.
- Live DB health check passed in the latest read-only audit with 44 markets, 43 open markets, 1 resolved market, 3664 snapshots, 7 ADS predictions, 8 forecast decision records, 0 scored ADS predictions, and 0 unscored resolved ADS predictions.
- True-live readiness with `predquant.ads_production_handlers:build_stage_handlers` blocks on `calibration_debt_not_cleared`.
- The same true-live readiness command accepted a caller-supplied placeholder SCAE delta ref as a counted ref while still blocking on CAL-001. CAL-001 masks the issue today; true readiness should reject placeholder/non-manifest refs directly.
- Bounded pilot scoreable readiness with `predquant.ads_production_pilot_handlers:build_stage_handlers` is still `ok=true`, which is useful for fixture/pilot plumbing but not evidence of the v2 intelligence path.
- The latest live DB real-runtime canary report still reflects pilot artifacts and fails true-runtime expectations with QDT/runtime and protected-delta issues.
- A scratch clone true-production canary using `predquant.ads_production_handlers:build_stage_handlers` and fresh OpenClaw OAuth Decomposer transport completed all 13 stages non-scoreably with:
  - active runs after: 0,
  - active leases after: 0,
  - unresolved manifests: 0,
  - stage error events: 0,
  - forecast decision records delta: +1,
  - market predictions delta: +0,
  - QDT model runtime evidence present for `gpt-5.5-high` with `fixture_mode=false`,
  - Decomposer consumed deterministic AMRG relationship hints in the final post-cleanup canary,
  - Researcher classification blocked with `blocked_until_certified_retrieval`.
- The same clone canary with `--require-researcher-model-executed` failed as expected with `real_runtime_canary:researcher_model_runtime_not_verified`.
- A later live-shaped clone audit first failed safely at decomposition with `no such column: qdt_artifact_id`; current Decomposer persistence now includes compatibility upgrade code, and the final post-cleanup clone canary completed against the live-shaped clone without the QDT table reset workaround.
- Pipeline control remains disabled after bounded runs, and the live DB has no active runs or leases.
- Storage maintenance reports `apply_required=true` even though retention candidates are currently zero; this is a warning/maintenance item, not the intelligence blocker.
- CAL-001 remains blocked for continuous/full production because there are 0 scoreable resolved/scored ADS predictions, no first-100 trace completeness evidence, no tail/regime/protected-component diagnostics, and no pointer-stability evidence.

Important memory context:

- `memory/2026-06-26.md#L72-L93`: the original architecture audit identified the skeleton as healthy and the intelligence layer as the key gap.
- `memory/2026-06-26.md#L94-L143`: prior implementation work was proceeding in strict phase order through Phase 6, with Phase 7 real retrieval/sufficiency as the next major blocker.

Specification basis:

- `autonomous-decomposition-swarm-architecture-spec---dbda0f1c----c13d6bea-f02f-4991-8d2c-d69ad5a7dc5a.md` makes SCAE the only live numeric authority, constrains AMRG to non-authoritative context/anchor effects, requires live GPT 5.5 high decomposition/research lanes, and requires retrieval sufficiency before classification/SCAE.
- `orchestrator/plans/autonomous-decomposition-swarm-implementation-plan.md` keeps the same phase order. This plan now treats Phases 0-6 as substantially implemented in the working tree and Phase 7 as the current critical path.

### Grounding Observations From Current Audit

These observations are the reason the plan below emphasizes retrieval, positive runtime evidence, and release-safe persistence over new architecture:

1. The true-production handler exists and can complete a bounded non-scoreable clone run, so the runner/control-plane skeleton should be extended rather than replaced.
2. The true-production retrieval path still invokes `build_live_retrieval_packet_from_candidates()` with empty `fetched_candidates`, `search_candidate_urls`, and `native_research_candidates`; that is the immediate runtime blocker.
3. The Researcher OpenClaw runtime adapter and barrier checks exist, but strict canary evidence fails with `researcher_model_runtime_not_verified` because retrieval blocks before Researcher dispatch.
4. The runtime-bundle-ready verification path still needs to consume accepted sidecars and direction/quality verification artifacts instead of relying on pilot-style certified reconciliation rows over the retrieval packet.
5. AMRG vector runtime is present but observed as unavailable in the audit environment; AMRG assist was observed as `not_requested`.
6. True-readiness mode currently needs stronger positive-evidence checks: manifest-derived SCAE delta refs, actual researcher runtime bundle refs, source-populated retrieval packets, and non-placeholder runtime provenance.
7. QDT persistence compatibility must be release-proven against live-shaped DB clones; the observed `qdt_artifact_id` failure is a cutover risk until the upgrade path is demonstrated without clone-only surgery.

## Current Architecture Readiness

### Strong Surfaces

1. **Control plane and runner**
   - `orchestrator/scripts/predquant/ads_pipeline_runner.py` has policy, stage order, non-executing mode, single-case AUTO-003, bounded multi-case AUTO-005, stop/drain handling, duplicate forecast protections, active-run/lease refusal, and per-stage handler contracts.
   - `StageHandlerResult` is a good narrow adapter boundary for new specialist runtime handlers.

2. **Case leasing and duplicate prevention**
   - `ads_case_selector.py` guards new leases behind `pipeline_enabled`, records leases, and supports skipping markets with existing ADS predictions.

3. **Manifest handoffs**
   - `ads_handoff.py` and `ads_handoff_resolver.py` provide persisted manifests, digest/path validation, strict stage-output resolution, and validation refs.
   - Production-readiness handlers already prove a full strict-manifest chain can run.

4. **True-production handler shell**
   - `predquant.ads_production_handlers:build_stage_handlers` now forces `scoreable_pilot=false`, `decomposer_runtime=true`, `live_retrieval_runtime=true`, `live_fixture_retrieval=false`, `researcher_swarm_openclaw_runtime=true`, and `amrg_vector_runtime=true`.
   - The bounded clone canary proved the handler can run all stages non-scoreably without leaking active runs, active leases, or scoreable predictions.

5. **Decomposer model-runtime path**
   - The Decomposer runtime path can emit a model-runtime call record, model-executed QDT artifact, and handoff provenance for `gpt-5.5-high`.
   - The bounded post-cleanup clone canary proved handler/runtime plumbing with fresh OpenClaw OAuth Decomposer transport.

6. **Live readiness and scheduler gates**
   - `ads_live_readiness.py` checks health, active runs/leases, storage, calibration debt, handler policy, and bounded calibration-debt canary limits.
   - `run_ads_operational_scheduler.py` can require readiness and disable after bounded runs.

7. **Operator and maintenance surfaces**
   - `report_ads_handoffs.py`, `maintain_ads_storage.py`, `run_ads_scoring_calibration_loop.py`, and health checks exist.
   - Storage maintenance reports retention candidates and DB/WAL sizes.

8. **SCAE**
   - SCAE is already positioned correctly as the only numeric forecast authority.
   - Prior/evidence/netting/missingness/conditional/interval/persistence tests pass.
   - Persistence bridge writes scoreable `market_predictions` with prediction-time market baseline.

9. **Decomposer and Researcher contract layers**
   - Decomposer has QDT schema validation, structural validation, sufficiency requirements, no-probability restrictions, model-lane metadata, and persistence helpers.
   - Researcher Swarm has retrieval packets, breadth/sufficiency structures, assignment schemas, isolation audits, sidecar validation, classification matrix, verification, coverage, escalation, and persistence helpers.
   - Researcher Swarm now has an OpenClaw runtime adapter and runtime bundle validation/barrier contracts, but it has not yet been exercised end-to-end because retrieval blocks first.
   - AMRG now has live descriptor/vector runtime code paths with explicit unavailable diagnostics.

### Primary Weaknesses

1. **Live retrieval transport is the current hard blocker**
   - The true-production retrieval handler calls the live retrieval packet builder with empty `fetched_candidates`, empty `search_candidate_urls`, and empty native candidates.
   - The retrieval materializer can validate and certify supplied evidence, but it is not yet wired to a real direct URL, search, web fetch, curated registry, or native candidate discovery transport in the production handler.
   - The clone canary therefore correctly records `retrieval_sufficiency_not_certified` and blocks Researcher execution.

2. **Researcher runtime exists but is not yet proven in the full pipeline**
   - The OpenClaw runtime adapter and bundle validators exist.
   - The strict clone canary with `--require-researcher-model-executed` fails because no researcher bundle or sidecars can exist while retrieval is uncertified.
   - Passing that strict canary should be the Phase 8 completion criterion.

3. **Verification-to-SCAE mapping is still incomplete for true runtime**
   - SCAE itself is healthy.
   - The production verification path still needs to consume accepted runtime sidecars/classification matrices, direction/quality verification artifacts, and reconciliation proofs before building SCAE evidence deltas.
   - A runtime-bundle-ready path must not reuse pilot-style certified rows over the retrieval packet.

4. **AMRG vector and assist are partially live but not operationally ready**
   - The AMRG vector path now builds descriptors and attempts the local Ollama route, but the audit environment reported `vector_status=unavailable` and `preflight_status=unavailable`.
   - AMRG model assist remains `not_requested` unless a response file or transport is configured.
   - The final post-cleanup canary showed Decomposer hint-consumption metadata for deterministic AMRG relationship hints.

5. **True readiness still needs positive evidence hardening**
   - True-readiness mode correctly rejects pilot handlers and blocks on CAL-001.
   - It should also derive QDT, retrieval, researcher, AMRG, and SCAE evidence from the latest real-runtime canary manifests instead of trusting optional CLI-supplied signals or placeholder refs.

6. **QDT persistence compatibility is a release risk until re-proven**
   - A live-shaped clone audit exposed `no such column: qdt_artifact_id` during decomposition before a clone-only reset workaround.
   - Current Decomposer persistence code includes upgrade helpers, but the release gate should require a live-shaped clone canary without schema surgery.

7. **CAL-001 blocks full production**
   - This is expected. There are pilot predictions, but no resolved/scored ADS prediction evidence yet.
   - Continuous scoreable operation should remain blocked until CAL-001 evidence exists.

## AMRG Assessment

AMRG remains one of the healthier subsystems architecturally. It is not merely a stub. It has active-safe market descriptors, deterministic candidate generation, live vector-runtime plumbing, vector-neighbor contracts, advisory model-assist packet/output validation, refresh lifecycle, strict-precedence anchor validation surfaces, shared-cache reuse eligibility, and persistence.

### AMRG Strengths

1. **Active-safe candidate contract**
   - Rejects inactive/resolved/post-cutoff markets and unsafe fields such as raw payloads, outcomes, scoring, replay, predictions, and production forecast values.
   - Candidate sources include platform family, entity match, contract source, shared resolution source, current exposure, generic theme, and optional vector neighbor.

2. **Effect boundaries are explicit**
   - Weak context can only provide decomposition context hints.
   - Deterministic context candidates can add retrieval query hints.
   - Validated strict-precedence anchors can provide condition-scoped anchor validation input.
   - Probability authority, SCAE deltas, QDT selection/repair, forecast writes, fair values, and interval authority are forbidden.

3. **Vector lane is implemented with fail-closed diagnostics**
   - `amrg_vector_embedding` is local Ollama `BAAI/bge-base-en-v1.5`.
   - Vector unavailable diagnostics are non-blocking.
   - Vector candidates are capped and weak-context-only.
   - The current model-lane policy requires provider `ollama`, route `ollama/local`, and download command `ollama pull BAAI/bge-base-en-v1.5`.
   - The clone canary built 43 descriptors and 42 candidate descriptors, then recorded the Ollama vector route as unavailable without blocking deterministic AMRG.

4. **Advisory model assist is bounded**
   - AMRG model assist can classify existing candidate rows using fixed vocabularies.
   - It cannot create concepts, promote edges, author probabilities, repair QDTs, or affect SCAE directly.

5. **Refresh and downgrade lifecycle exists**
   - Stale promoted effects downgrade to weak context unless refreshed.
   - Refresh results can retain deterministic effects when fresh and safe.

6. **Persistence is broad**
   - Writes candidate sets, peer rows, relationship slices, graph-safety slices, refresh events, prior-anchor slices, vector descriptors, vector index snapshots, vector neighbor slices, and model-assist provenance.

### AMRG Gaps

1. **Vector runtime depends on operator-local service readiness**
   - The code path is present, but the audited environment did not have a reachable/ready Ollama BGE route.
   - Operator preflight needs to make the unavailable state obvious before a run, not only after the AMRG stage.

2. **AMRG model assist is not default-wired**
   - Output validation exists, but there is no default OpenClaw OAuth assist invocation in the true-production handler.
   - `not_requested` is acceptable only when the run policy explicitly treats assist as optional.

3. **Strict-precedence anchors are not exercised by real QDTs**
   - Anchor contracts can be validated, and the final audited Decomposer QDT consumed deterministic AMRG relationship hints, but it did not yet request real question-specific anchor dependency contracts.

4. **Refresh policy still needs a promoted-effect live proof**
   - Refresh logic exists, and the clone canary reported `fresh_no_refresh_needed`.
   - Promoted-effect refresh and downgrade paths still need a live run that actually promotes and refreshes effects.

5. **Shared cache reuse is contract-ready but not integrated into live retrieval**
   - Eligibility logic exists and is tested.
   - True-production live retrieval is still not sourcing real candidate URLs or cache-aware source material.

6. **Operator visibility is incomplete for AMRG quality**
   - The AMRG operator report is useful, but readiness/canary gates should consume its key fields: vector status, model-assist status, relationship effects, refresh status, strict-precedence anchor state, and Decomposer hint consumption.

## Readiness Verdict

Architecture readiness excluding full live evidence intelligence: **high for bounded canary/control-plane operations, medium for non-scoreable true-runtime skeleton runs, low for unattended scoreable true production.**

The current architecture is suitable as the base for the real v2 pipeline. It should not be replaced. The next work should wire real retrieval transport, source sufficiency, Researcher execution, and SCAE evidence intake through the existing runner, manifests, AMRG context, and readiness gates.

The current pipeline is **not** ready for unattended scoreable live operation because:

- Retrieval is not producing source-populated, sufficiency-certified live evidence.
- Researcher execution is therefore not proven in the end-to-end true-production path.
- SCAE is not yet receiving verified runtime classification-derived evidence deltas.
- AMRG vector/model-assist live dependencies are either unavailable or not requested in the audited run.
- True-live readiness needs manifest-derived positive evidence requirements beyond optional signal inputs.
- QDT persistence compatibility needs a clean live-shaped clone proof without table reset/workaround.
- CAL-001 is still blocked.

## Implementation Plan

### Progress Status After 2026-06-27 Audit

| Phase | Current status | Next focus |
| --- | --- | --- |
| 0 - Pilot/production semantics | Substantially implemented | Keep pilot lane available, but prevent pilot artifacts from satisfying true-production readiness. |
| 1 - Shared model runtime | Substantially implemented for Decomposer fresh-route proof | Extend the same OpenClaw OAuth runtime provenance to remaining model-backed lanes. |
| 2 - OpenClaw execution boundary | Partially implemented | Reuse for Researcher and AMRG assist with explicit provenance and failure classes. |
| 3 - Evidence collection runtime contract | Partially implemented | Connect source discovery/fetch attempts to persisted retrieval candidates. |
| 4 - Real Decomposer execution | Substantially implemented | Require question-specific QDT, fresh-route evidence when policy requires it, and live-shaped DB migration compatibility. |
| 5 - AMRG-to-Decomposer context | Partially implemented | AMRG hint consumption is now proven; anchor dependency requests still need a non-fixture proof. |
| 6 - AMRG vector/assist | Vector path implemented, assist optional/not requested | Add operator preflight, ready-route canary, and default/explicit assist policy. |
| 7 - Real retrieval/sufficiency | Current hard blocker | Wire direct URLs, search/provider candidates, web fetch, native discovery, and sufficiency certificates into the true handler. |
| 8 - Researcher execution | Runtime adapter and barriers exist, end-to-end blocked | Pass strict canary with `--require-researcher-model-executed`. |
| 9 - Verification to SCAE | Deterministic helpers exist, true runtime intake incomplete | Map accepted sidecars/classification verification into SCAE evidence delta refs. |
| 10 - True production handler | Handler shell exists and runs non-scoreably | Replace empty retrieval and pilot-style verification shortcuts before scoreable use. |
| 11 - Canary ladder | Real-runtime report exists | Gate on retrieval sufficiency, researcher execution, AMRG diagnostics, and SCAE delta refs. |
| 12 - Observability/readiness | Many reports exist | Derive true-readiness from latest manifests/canary report, not caller-provided placeholders. |
| 13 - CAL-001 expansion | Blocked | Accumulate real scored evidence only after true intelligence path is scoreable. |

### Phase 0 - Preserve Pilot Lane And Add Production Semantics

Goal: keep the existing production-pilot path useful without letting it masquerade as true v2 intelligence.

2026-06-27 audit status: this phase is substantially implemented. Pilot readiness can still pass for bounded fixture/scaffolding work, while true-live readiness rejects pilot handlers and currently blocks on CAL-001. The remaining gap is to make true readiness derive positive runtime evidence from manifests/canary reports, not only from caller-supplied flags.

Modify existing surfaces:

- `orchestrator/scripts/predquant/ads_production_readiness_handlers.py`
- `orchestrator/scripts/predquant/ads_production_pilot_handlers.py`
- `orchestrator/scripts/predquant/ads_live_readiness.py`
- tests in `orchestrator/scripts/tests/test_ads_live_readiness.py`

Tasks:

1. Rename/report the deterministic QDT mode as `pilot_fixture_decomposer_contract_adapter`.
2. Add a readiness distinction:
   - `pilot_scoreable_readiness`: allows bounded production-pilot under calibration-debt controls.
   - `true_scoreable_live_readiness`: requires real Decomposer and Researcher model execution provenance.
3. Add a hard issue when a non-pilot scoreable run reports:
   - deterministic QDT adapter mode,
   - metadata-only researcher context,
   - structured-market-metadata certification as the only research input.
4. Add test coverage proving bounded pilot still works but true live readiness blocks pilot handlers.
5. Ensure true-production readiness treats pilot scoreable readiness as non-transferable evidence:
   - pilot `ok=true` may prove runner/persistence plumbing only,
   - it must not clear QDT runtime, retrieval sufficiency, researcher runtime, SCAE evidence delta, or CAL-001 gates.
6. In readiness output, report which evidence came from live manifests/canary reports and which evidence was provided by CLI override or placeholder input.

Acceptance:

- Existing pilot tests still pass.
- A true-live readiness report refuses the pilot handler even if CAL-001 canary bypass is requested.
- Operator output names the lane clearly as pilot/fixture.
- True-production readiness cannot be satisfied by pilot artifacts, transport-response-only evidence when fresh live transport is required, or placeholder SCAE delta refs.

### Phase 1 - Add Shared Model Runtime Transport

Goal: provide a reusable model-call adapter for Decomposer, Researcher, and native research without embedding provider details throughout the pipeline.

2026-06-27 audit status: this phase is substantially implemented for Decomposer and enough to validate handler/runtime plumbing with fresh OpenClaw OAuth transport. AMRG assist/native research/researcher execution still need consistent runtime provenance and failure handling.

Modify existing surfaces:

- New small module under a current owner, preferably:
  - `decomposer/scripts/ads_decomposer/model_runtime.py`, or
  - shared Orchestrator helper if OpenClaw model invocation must live under Orchestrator.
- `decomposer/scripts/ads_decomposer/handoff.py`
- `researcher-swarm/scripts/researcher_swarm/model_context.py`
- `orchestrator/plans/autonomous-decomposition-swarm-model-lane-policy.json` only if policy fields need clearer runtime route metadata.

Tasks:

1. Implement a `model-runtime-call/v1` abstraction that resolves existing model-lane policy and calls the configured `openai/gpt-5.5-high` route.
2. Store:
   - model lane id,
   - resolved model id,
   - provider route,
   - prompt template id and sha,
   - input manifest refs,
   - request/response artifact hashes,
   - output schema version,
   - timeout,
   - retry count,
   - repair count,
   - fixture/live mode,
   - forbidden-output scan result,
   - latency/token/status metadata when available.
3. Apply runtime policy:
   - QDT generation timeout: 180 seconds,
   - leaf researcher/classifier timeout: 240 seconds,
   - native research candidate discovery timeout: 180 seconds,
   - retry at most once for transport errors,
   - bounded JSON/schema repair at most once,
   - no retry for forbidden probability/fair-value/SCAE-delta output.
4. Add no-probability/fair-value/SCAE-delta scanner for all model outputs.
5. Add offline fixture mode for unit tests, but require explicit fixture mode in metadata.
6. Add route-specific readiness checks that distinguish:
   - fixture response,
   - transport-response file,
   - fresh OpenClaw OAuth model call,
   - provider unavailable,
   - schema repair,
   - forbidden-output rejection.
7. Reuse the same runtime provenance vocabulary for Decomposer, native candidate discovery, Researcher NLI sidecars, AMRG assist, and any source-metadata assist.
8. Add canary/report criteria that make transport-response proof acceptable for contract testing but insufficient for fresh live-route cutover.

Acceptance:

- Unit tests can run without network/model access using fixture responses.
- Runtime provenance can represent both `metadata_only` and `model_executed`.
- Forbidden probability fields are rejected before downstream validation.
- Tests cover fixture mode, live-mode provenance, retry exhaustion, schema repair once, and fail-closed forbidden output.
- A canary can separately report "runtime contract proven" and "fresh external route proven" for each model-backed lane.

### Phase 2 - GPT Runtime And Subagent Wiring Contract

Goal: make the intended intelligence import path explicit before wiring live model execution.

2026-06-27 audit status: the decomposition runtime boundary and Researcher Swarm runtime adapter/barrier contracts exist, but the full control-plane launch/result path has not been proven end to end because retrieval blocks before researcher dispatch. This phase remains partially implemented until a strict canary proves researcher subagent execution and terminal leaf results.

Ownership rules:

1. **Decomposer owns QDT generation**
   - The decomposition stage must call the Decomposer runtime, not an ad hoc impermanent session as the artifact owner.
   - The Decomposer runtime may use a short-lived model/session transport internally if that is the available OpenClaw execution path, but the durable owner remains `ADS Decomposer`.
   - The only acceptable stage output is a Decomposer-owned, manifest-backed `question-decomposition/v1` artifact with model execution provenance and deterministic validation results.
   - Decomposer must not spawn researcher subagents, browse freely, write forecasts, author probabilities, author SCAE deltas, or continue to downstream stages directly.
2. **Researcher Swarm owns leaf subagent coordination**
   - Researcher Swarm builds one primary `leaf-research-assignment/v1` per dispatchable QDT leaf.
   - Orchestrator/control-plane code is the only launch authority for OpenClaw subagent sessions.
   - `researcher_swarm.subagents` should continue to build spawn plans and validation artifacts; actual OpenClaw session creation belongs to the control plane.
3. **One subagent per leaf by default**
   - Every QDT leaf that reaches classification dispatch gets a fresh leaf researcher subagent by default.
   - Extra subagents for the same leaf are allowed only through the existing escalation policy.
   - The default concurrency cap remains `max_concurrent_leaf_researchers_per_case = 5`; extra leaves queue rather than sharing context.
4. **Leaf subagents are leaf-scoped researchers/classifiers**
   - Leaf subagents consume only their own assignment packet, allowed evidence/snippet refs, prompt/schema refs, and model lane metadata.
   - Leaf subagents may use their assigned certified/classified evidence to do bounded follow-up research for that same leaf, including source chasing, contradiction checks, negative checks, and missing-field searches.
   - Leaf-scoped follow-up research must use approved retrieval/native-research transports, stay within the leaf's assignment and evidence family, and write candidate supplemental evidence refs rather than silently expanding global context.
   - New evidence discovered by a leaf subagent does not count until deterministic resolver stages validate source class/family, claim family, temporal safety, access state, breadth, contradiction/negative-check status, and sufficiency.
   - Leaf subagents must not see sibling assignments, see peer outputs, see aggregate summaries, see SCAE refs, see decision/forecast refs, see replay/scoring refs, or see outcome refs.
   - If assigned evidence plus bounded follow-up research is still insufficient, the leaf returns a blocker/escalation signal; bounded retrieval expansion or an additional assignment happens only through policy-controlled escalation.
5. **Pipeline barrier after fan-out**
   - The pipeline must not advance from researcher classification to verification/SCAE until every dispatchable QDT leaf has a terminal state:
     - accepted sidecar/classification,
     - structural-unanswerability proof,
     - explicit insufficient-evidence blocker,
     - or policy-approved waived/non-dispatchable status.
   - Any active, timed-out, contaminated, missing, or invalid leaf subagent blocks the case from SCAE and decision persistence.
   - The barrier result must be persisted as a compact `leaf-research-barrier/v1` or equivalent reconciliation artifact with assignment refs, subagent session refs, terminal status per leaf, timeout/retry state, and proceed/block decision.

Implementation surfaces:

- Decomposer:
  - `decomposer/scripts/bin/run_decomposition.py`
  - `decomposer/scripts/ads_decomposer/model_runtime.py`
  - `decomposer/scripts/ads_decomposer/qdt.py`
  - `decomposer/scripts/ads_decomposer/persistence.py`
- Researcher Swarm:
  - `researcher-swarm/scripts/bin/build_leaf_research_assignments.py`
  - `researcher-swarm/scripts/bin/spawn_leaf_researchers.py`
  - `researcher-swarm/scripts/bin/run_researcher_swarm.py`
  - `researcher-swarm/scripts/bin/validate_researcher_context_isolation.py`
  - `researcher-swarm/scripts/bin/validate_researcher_sidecars.py`
  - `researcher-swarm/scripts/bin/reconcile_research_sufficiency.py`
  - `researcher-swarm/scripts/researcher_swarm/subagents.py`
  - `researcher-swarm/scripts/researcher_swarm/isolation.py`
  - `researcher-swarm/scripts/researcher_swarm/coverage.py`
  - `researcher-swarm/scripts/researcher_swarm/persistence.py`
- Orchestrator/control plane:
  - production handler stage that wakes Decomposer,
  - production handler stage that requests leaf researcher spawn plans,
  - OpenClaw subagent/session adapter that launches leaf subagents,
  - barrier loop that waits for all terminal leaf results before verification/SCAE.

Runtime requirements:

1. Add an OpenClaw GPT transport adapter analogous to the Ollama embedding adapter:
   - resolve model lane from `autonomous-decomposition-swarm-model-lane-policy.json`,
   - require `decomposer_qdt_generation` and `researcher_leaf_nli_classification` to resolve to `openai/gpt-5.5-high`,
   - record provider route, model id, prompt template id/hash, input artifact refs, request artifact hash, response artifact hash, output schema version, status, token/latency metadata where available, and fixture-vs-live mode.
2. Add an OpenClaw subagent adapter:
   - create one impermanent subagent/session per leaf assignment,
   - pass only the validated assignment payload and allowed refs,
   - expose only approved leaf-scoped research tools/transports and configured budgets,
   - record `subagent_session_ref`,
   - write/update the corresponding `researcher-context-isolation/v1` audit,
   - collect sidecar and candidate supplemental evidence artifacts from each subagent,
   - enforce timeout/retry/cancel policy.
3. Add `leaf-subagent-execution-policy/v1` and `leaf-subagent-result/v1`:
   - max concurrent leaf subagents per case: 5,
   - queue extra leaves,
   - max wall time per leaf: 20 minutes,
   - status/heartbeat poll interval: 60 seconds,
   - retry at most once for transient launch/session failure,
   - never retry contaminated context, forbidden output, or invalid sidecar as if it were clean evidence.
4. Require subagent results to include sidecar refs, proposed supplemental evidence refs, tool-use summary, terminal status, timeout/cancel status, and isolation audit ref.
5. Add fail-closed checks:
   - no Decomposer output without `model_executed` provenance in true-production mode,
   - no leaf subagent launch without `launch_allowed=true`,
   - no leaf subagent result accepted in true-production mode unless runtime provenance shows `model_executed` with resolved model `openai/gpt-5.5-high`,
   - no sidecar acceptance if isolation audit shows contamination,
   - no verification/SCAE stage start until the barrier artifact says all leaves are terminal and sufficient or explicitly blocked.
6. Add an Orchestrator-owned researcher launch/result adapter proof:
   - consumes the current assignment bundle,
   - launches/collects isolated leaf researcher runtime results,
   - writes terminal sidecar/isolation/subagent refs,
   - hands those refs back to `run_researcher_swarm.py` validation,
   - records a barrier artifact that can be consumed by verification.
7. Make the current `researcher-classification-readiness-block` path explicitly non-scoreable and non-evidence for model execution.

Acceptance:

- Decomposition produces a Decomposer-owned QDT artifact even if an impermanent session is used as the GPT transport.
- Researcher Swarm produces one validated spawn plan entry per dispatchable QDT leaf.
- Control plane launches one fresh isolated subagent per leaf up to the concurrency cap and queues the rest.
- A leaf subagent can use assigned evidence to discover bounded supplemental evidence, but that evidence is ignored until resolver/sufficiency validation admits it.
- A deliberately slow/missing leaf keeps the case blocked before verification/SCAE.
- A contaminated leaf subagent output fails closed and blocks scoreable prediction.
- A successful run shows Decomposer provenance, per-leaf subagent refs, isolation audits, sidecars, and a passing barrier artifact in the handoff report.
- The strict clone canary with `--require-researcher-model-executed` passes only after Phase 7 retrieval sufficiency enables real Researcher dispatch.

### Phase 3 - Evidence Collection Runtime Contract

Goal: make evidence collection a first-class runtime stage, separate from classification and separate from SCAE probability authority.

2026-06-27 audit status: the contract is well specified and many deterministic validation structures exist, but the true-production handler currently reaches the retrieval materializer with empty candidate lists. The phase is therefore contract-rich but runtime-incomplete; its remaining work collapses into the Phase 7 transport and sufficiency blocker.

Ownership rules:

1. **Retrieval owns initial evidence collection**
   - Retrieval starts from QDT leaves, case contract, evidence packet, market rules, cutoff times, policy profile, and AMRG hints.
   - Retrieval is responsible for candidate discovery, source capture, chunk/span extraction, metadata normalization, temporal eligibility, source-family and claim-family resolution, breadth coverage, contradiction checks, negative checks, missingness diagnostics, expansion/fallback attempts, and `RET-008` sufficiency certificates.
   - Retrieval may use browser/web-fetch, native GPT research, structured feeds, DB-backed context, and manual fixture transport in fixture mode.
   - Native GPT research is a candidate discovery/query expansion transport only. It is not final source metadata authority, not final claim-family authority, not final temporal authority, and not a probability author.
2. **Leaf subagents may collect supplemental evidence only within their leaf**
   - A leaf subagent receives a leaf assignment, admitted evidence refs, allowed snippet/span refs, explicit missing fields, allowed transports, budgets, and forbidden context refs.
   - It may chase sources, look for contradictions, run negative checks, fill missing required fields, and discover candidate supplemental evidence for that same leaf.
   - It must write candidate supplemental evidence artifacts rather than silently folding new evidence into its classification.
   - Supplemental evidence must pass deterministic normalization/resolution before it can affect coverage, sufficiency, verification, or SCAE readiness.
3. **Classification interprets admitted evidence; it does not admit evidence**
   - Source metadata classifier assist may provide compact hints, but deterministic resolvers remain final authority for source class/family, claim family, temporal safety, access state, breadth, contradiction, negative checks, and sufficiency.
   - Leaf researcher/classifier sidecars may classify the direction, strength, confidence, quality, and condition scope of admitted evidence.
   - Any sidecar that relies on unadmitted evidence must fail closed or route that evidence through supplemental normalization first.
4. **Evidence barrier comes before verification/SCAE**
   - A case cannot proceed to verification/SCAE until every dispatchable leaf has either sufficient admitted evidence and accepted classification coverage, a structural-unanswerability proof, an explicit insufficient-evidence blocker, or policy-approved waiver.
   - The barrier artifact must include initial retrieval packet refs, admitted evidence refs, supplemental candidate refs, supplemental admission/rejection refs, per-leaf sufficiency status, and proceed/block decision.

Concrete live retrieval spec:

1. **Source thresholds are leaf-policy driven, with fail-closed defaults**
   - The Decomposer must emit `research_sufficiency_requirements` for every dispatchable leaf.
   - If a dispatchable leaf lacks source/claim/freshness thresholds, retrieval must fail closed before classification rather than silently using a weak default.
   - Live source-of-truth or critical leaves require:
     - protected primary/official source required when one exists,
     - at least 5 admitted evidence items,
     - at least 3 independent source families,
     - at least 3 independent claim families unless the leaf is a single-source official-rules/source-of-truth leaf,
     - at least 2 temporally fresh sources for active/current event leaves,
     - at least 1 independent corroborating source family outside the protected primary family when available,
     - contradiction search attempted,
     - required negative checks attempted.
   - Live direct-evidence, catalyst, or high-weight leaves require:
     - at least 5 admitted evidence items,
     - at least 3 independent source families,
     - at least 3 independent claim families,
     - at least 2 temporally fresh direct sources,
     - at least 1 source family from the required primary/official class when the leaf calls for direct event confirmation,
     - contradiction search attempted,
     - required negative checks attempted.
   - Live medium/normal leaves require:
     - at least 3 admitted evidence items,
     - at least 2 independent source families,
     - at least 2 independent claim families,
     - at least 1 temporally fresh source when the leaf purpose has a freshness requirement,
     - contradiction search attempted,
     - required negative checks attempted.
   - Live mechanics or rule-interpretation leaves require:
     - at least 2 admitted evidence items,
     - at least 1 official/market-rules source family,
     - at least 1 claim family,
     - freshness appropriate to the active rules/version,
     - an independent corroborating or archived/rules-copy source family when available,
     - protected-primary access/missingness recorded if official rules are unavailable.
   - Duplicate articles, syndicated copies, reposts, or pages from the same source family do not increase independent source-family breadth.
   - The live policy is intentionally stricter than the current canonical QDT minima. If the Decomposer emits weaker `research_sufficiency_requirements`, the retrieval executor must apply the live policy overlay and persist the effective thresholds used for dispatch.
2. **Direct URL capture precedes search**
   - Retrieval first fetches direct URLs from market rules, source-of-truth metadata, evidence packets, AMRG anchors, and structured feeds.
   - Direct URL fetch uses the OpenClaw web fetch transport shape: `openclaw.web_fetch({url, extractMode: "markdown", maxChars})`.
   - `web_fetch` is a URL fetch/extraction tool, not a search engine. Search/discovery must happen through the configured browser/search provider, native GPT candidate discovery, structured feeds, or AMRG hints that produce candidate URLs.
   - Each fetch writes a `browser-retrieval-attempt/v1` or equivalent attempt ref with requested URL, final URL, canonical URL, extraction status, content artifact ref, fetch time, and transport id.
3. **Search/discovery is bounded per leaf**
   - For each leaf, retrieval builds query variants from leaf text, required fields, required source classes, market terms, AMRG hints, contradiction prompts, and negative-check prompts.
   - Initial retrieval budget should target at least the leaf's minimum source-family and claim-family thresholds plus one spare candidate per required source class, capped by policy.
   - If thresholds are not met, `RET-008` may run targeted expansion up to `max_targeted_expansion_attempts`; after that the leaf blocks or produces structural-unanswerability/missingness proof.
4. **Models assist evidence discovery but do not admit evidence**
   - Native GPT research may propose candidate URLs, query expansions, and source leads.
   - Source metadata classifier assist may propose compact source/claim metadata hints.
   - Neither model path can admit evidence, certify sufficiency, decide temporal safety, decide claim/source-family final authority, or produce probabilities.
   - Deterministic resolvers must admit or reject each candidate before the evidence can reach classification, verification, or SCAE.
5. **Leaf subagent follow-up is supplemental retrieval**
   - Leaf subagents may fetch/check sources only within their leaf assignment and allowed transports.
   - Candidate evidence found by a subagent enters the same supplemental normalization and deterministic admission pipeline as initial retrieval.
   - Subagent classification may reference only admitted evidence ids; otherwise it must mark the evidence as proposed supplemental and wait for admission.

Freshness applicability:

- Current Decomposer code applies freshness when leaf purpose is one of `source_of_truth`, `direct_evidence`, `catalyst`, or `market_pricing`; static/background leaves generally get `min_temporally_fresh_sources = 0`.
- The live retrieval policy should treat that as the lower bound and require freshness whenever any of these are true:
  - the leaf asks about current event status, latest action, latest price/market state, official decision, filing/publication, live vote/count/status, injury/availability, policy/rate/economic release, exchange/listing status, or another value that can change after stale evidence;
  - the market is open and the relevant event/resolution window has not passed;
  - the leaf has required fields such as `event_status`, `event_timestamp`, `official_status`, `latest_value`, `current_price`, `policy_decision`, `resolution_status`, `candidate_status`, or `availability_status`;
  - the QDT marks the leaf purpose as `source_of_truth`, `direct_evidence`, `catalyst`, or `market_pricing`;
  - AMRG/retrieval hints indicate related markets or source anchors have changed since the last cached evidence.
- Freshness is not required, unless the Decomposer or live overlay explicitly says otherwise, for stable background/base-rate leaves, durable historical facts, fixed contract/rule text, or mechanics leaves whose current rules version has already been captured and whose source has not changed.
- A "fresh" source must both pass temporal eligibility and fall within the leaf's `recency_window_seconds` before `source_cutoff_timestamp`; live capture time alone does not make a source fresh if source publication/update time is unknown.
- If publication/update time is unknown, the evidence may be admitted for non-fresh dimensions but must not count toward the fresh-source requirement.
- If freshness is required and not met after targeted expansion, the leaf blocks with stale/missing-freshness reason codes rather than dispatching as sufficient.

Current source-count evaluation:

- Current canonical Decomposer sufficiency requirements already set minimum breadth:
  - `critical` and `high` leaves require 2 independent source families and 2 independent claim families.
  - `medium` and `low` leaves require 1 independent source family and 1 independent claim family.
  - `source_of_truth`, `direct_evidence`, `catalyst`, and `market_pricing` leaves require at least 1 temporally fresh source.
  - `source_of_truth` leaves require protected primary/official handling.
  - canonical max targeted expansion attempts are 3 unless a stricter leaf policy overrides them.
- These canonical minima are too low for live operations. They should remain as schema/template lower bounds, while the live retrieval policy overlay raises dispatch requirements to 3 source/claim families for critical/high leaves and 2 source/claim families for normal leaves.
- Current retrieval planning has larger target ranges in `_volume_tier_for_leaf()`:
  - critical/source-of-truth: 5 query variants, 80-120 raw candidates, 15-25 admitted evidence target, 5 tier-level expansion attempts;
  - high: 4 query variants, 50-80 raw candidates, 12-16 admitted target, 4 tier-level expansion attempts;
  - normal: 3 query variants, 30-50 raw candidates, 8-12 admitted target, 3 tier-level expansion attempts.
- Because canonical QDT requirements currently carry `max_targeted_expansion_attempts = 3`, the tier-level 4/5 expansion values are not actually used unless requirements omit or override that field.
- The raw/admitted target ranges are useful as upper-bound planning metadata, but they are too broad for the first live web-fetch implementation. The live v1 executor should use tighter fetch budgets, stop early once sufficiency is certified, and record budget exhaustion explicitly.
- Current tests prove a minimal browser-only cutover shape with 2 accepted evidence items per leaf: one direct official/source-of-truth item and one independent secondary item. That proves the admission/sufficiency shape, not real web-scale retrieval.

Real web retrieval execution algorithm:

1. **Build the per-leaf retrieval docket**
   - Load the QDT leaf, `research_sufficiency_requirements`, evidence packet, market rule URLs, AMRG hint refs, source cutoff, forecast timestamp, and policy budget.
   - Build primary query variants, contradiction query variants, and negative-check query variants using the existing query context builder.
   - Build a fetch budget from the leaf tier:
     - critical/source-of-truth: direct URL cap 15, primary search cap 45 fetched pages, contradiction cap 12, negative-check cap 6 per required check, admitted evidence target 8-15, admitted evidence cap 18;
     - high/direct-evidence/catalyst: direct URL cap 12, primary search cap 35 fetched pages, contradiction cap 10, negative-check cap 5 per required check, admitted evidence target 6-12, admitted evidence cap 14;
     - normal/medium: direct URL cap 10, primary search cap 24 fetched pages, contradiction cap 6, negative-check cap 3 per required check, admitted evidence target 4-8, admitted evidence cap 10;
     - mechanics/rules-only: direct URL cap 10, primary search cap 16 fetched pages, contradiction cap 4, negative-check cap 2 per required check, admitted evidence target 2-5, admitted evidence cap 8.
   - Stop fetching for a leaf as soon as all required source classes, source-family breadth, claim-family breadth, freshness, contradiction, negative-check, and protected-primary dimensions are satisfied.
2. **Fetch direct URLs first**
   - Direct candidates come from market metadata/rules, evidence packet hints, AMRG anchors, structured feeds, and official/source-of-truth registries.
   - For each direct candidate, call the OpenClaw fetch transport as a URL fetch:
     - `openclaw.web_fetch({url, extractMode: "markdown", maxChars})`
   - Persist a `browser-retrieval-attempt/v1` record with `navigation_mode = direct_url`, requested URL, final URL, canonical URL, extraction status, capture time, text/content artifact refs, and hash metadata.
   - Direct URL fetch failures must be classified as transient fetch failure, blocked/protected-primary missingness, paywall/access blocked, temporal failure, duplicate, or rejected.
3. **Run search/discovery only after direct URLs**
   - `openclaw.web_fetch` does not perform search by itself. Search must be provided by the configured browser/search provider, native GPT candidate discovery, structured feeds, AMRG hints, or curated registries that produce URLs.
   - For each query variant, request ranked candidate URLs from the configured search provider up to the leaf's primary search cap.
   - Fetch candidate URLs with `web_fetch`, persist attempt records with `navigation_mode = web_search` or `site_search`, then canonicalize and dedupe by canonical URL/content hash/source family.
   - Prefer official/primary and direct domain results before independent secondary results when the leaf requires protected primary handling.
4. **Extract evidence candidates**
   - For each fetched page, persist page content artifact, chunks, spans, visible date candidates, title/domain metadata, and candidate atomic claims.
   - Candidate claims must be bounded to source spans; spanless or multi-claim proposals are rejected or split before admission.
   - Candidate evidence must carry retrieval transport, transport attempt ref, canonical URL, content hash, source class candidate, source family candidate, claim family candidates, temporal metadata, and source-access status.
5. **Resolve metadata deterministically**
   - Resolve source class from market rules/registry/domain/content heuristics first; optional source-metadata classifier hints are advisory only.
   - Resolve source family by canonical publisher/API/wire family. Reuters/AP copies, syndicated mirrors, duplicated feeds, and same-domain reposts count once.
   - Resolve claim family by normalized atomic claim tuple. Repeated same-claim articles count once; contradictory polarity joins the contradiction family.
   - Resolve temporal safety using published/updated/source timestamps against source cutoff and forecast timestamp; live capture time alone is not enough when source time is unknown.
6. **Run contradiction and negative checks**
   - For leaves with `contradiction_search_required`, run the generated contradiction queries and persist contradiction-search attempts even when no contradiction is found.
   - For each required negative check, run its generated queries and persist negative-check attempts.
   - Contradictory or negative evidence follows the same admission pipeline and can satisfy contradiction/negative-check coverage without being treated as supportive evidence.
7. **Certify or expand**
   - Build retrieval breadth coverage from admitted candidates.
   - If required breadth is not met, run targeted expansion up to `max_targeted_expansion_attempts`, focused only on missing dimensions such as protected primary, source-family diversity, claim-family diversity, freshness, contradiction, or negative checks.
   - If expansion still fails, emit `blocked_insufficient_research`, `blocked_missing_breadth`, protected-primary missingness, or structural-unanswerability proof. Do not dispatch classification as sufficient.
8. **Hand off only admitted evidence**
   - Classification assignments receive admitted evidence refs, chunk refs, span refs, source metadata refs, sufficiency certificate refs, and explicit blockers/missingness.
   - Rejected/omitted candidates remain in the evidence docket for audit, but do not become classifier evidence.
   - Leaf subagent supplemental evidence repeats this same candidate -> fetch -> normalize -> admit/reject -> updated sufficiency path.

Implementation surfaces:

- `researcher-swarm/scripts/researcher_swarm/retrieval.py`
- `researcher-swarm/scripts/researcher_swarm/supplemental.py`
- `researcher-swarm/scripts/researcher_swarm/metadata_resolver.py`
- `researcher-swarm/scripts/researcher_swarm/coverage.py`
- `researcher-swarm/scripts/researcher_swarm/classification.py`
- `researcher-swarm/scripts/researcher_swarm/subagents.py`
- `researcher-swarm/scripts/bin/build_retrieval_packet.py`
- `researcher-swarm/scripts/bin/run_browser_retrieval.py`
- `researcher-swarm/scripts/bin/run_native_gpt_research.py`
- `researcher-swarm/scripts/bin/reconcile_research_sufficiency.py`
- `orchestrator/scripts/predquant/ads_production_readiness_handlers.py` or a successor production handler module that replaces the pilot/query-plan retrieval branch.

Tasks:

1. Replace live `structured_market_metadata_pilot_retrieval` with a real retrieval executor that can call approved transports and persist evidence/chunk/span/claim/source artifacts.
2. Add transport adapters for browser/web-fetch and native GPT research that return candidate records only.
3. Admit evidence only through deterministic source/claim/temporal/breadth/missingness validators.
4. Add supplemental evidence intake from leaf subagents and route it through the same deterministic validators.
5. Add a leaf evidence docket artifact containing initial admitted evidence, rejected/omitted candidates, supplemental candidates, supplemental admission results, and sufficiency status.
6. Enforce that classifier sidecars reference only admitted evidence ids unless they are explicitly proposing supplemental evidence.
7. Add tests for source chasing, contradiction search, negative check search, supplemental candidate rejection, and no-SCAE/no-probability leakage.
8. Add source-attempt persistence for the empty-candidate case seen in the audit:
   - distinguish "no candidates supplied",
   - "provider unavailable",
   - "fetch attempted and failed",
   - "candidate rejected",
   - "candidate admitted but insufficient".
9. Require the retrieval stage manifest to expose source-attempt counts and admitted evidence counts before Researcher dispatch can be considered.

Acceptance:

- A live-shaped fixture with no direct sources blocks before classification/SCAE.
- A live-shaped fixture with sufficient official/direct evidence reaches classification with admitted evidence refs and a passing sufficiency certificate.
- A leaf subagent can discover a supplemental official source and have it admitted only after deterministic validation.
- A leaf subagent that uses unadmitted evidence in classification fails closed.
- Handoff report shows evidence docket refs before sidecar/classification refs.
- The current empty-candidate true-production retrieval path is no longer able to look like a normal ready retrieval packet; it must be a clear blocker with remediation diagnostics.

### Phase 4 - Implement Real GPT 5.5 High Decomposer

Goal: replace template QDT generation with question-specific QDT generation while preserving deterministic validation.

2026-06-27 audit status: this phase is substantially implemented in the current working tree. The final scratch clone true-production canary produced QDT model-runtime evidence for `gpt-5.5-high` through fresh OpenClaw OAuth transport, and the live-shaped DB clone exercised the QDT persistence migration guard without a table reset workaround. The phase is complete for Decomposer cutover; remaining cutover risk sits downstream in retrieval sufficiency, Researcher execution, and SCAE evidence intake.

Modify existing surfaces:

- `decomposer/scripts/bin/run_decomposition.py`
- `decomposer/scripts/ads_decomposer/qdt.py`
- `decomposer/scripts/ads_decomposer/handoff.py`
- `decomposer/scripts/ads_decomposer/persistence.py`
- `orchestrator/scripts/predquant/ads_production_readiness_handlers.py` or a new production handler module that reuses its manifest helpers.

Tasks:

1. Turn `run_decomposition.py` into a real entrypoint:
   - load decomposer handoff,
   - load referenced manifests/payloads,
   - construct `decomposer-qdt/v1` prompt,
   - call GPT 5.5 high through the shared runtime,
   - parse JSON,
   - validate QDT schema and no-probability boundary,
   - run bounded repair once if parsing/schema fails.
2. Prompt inputs should include:
   - macro question/title,
   - market description/rules/source-of-truth,
   - close/resolve timestamps and source cutoff,
   - side mapping and market reality constraints,
   - evidence packet,
   - profile context,
   - AMRG context/waiver,
   - instructions to produce a depth-2 QDT with concrete leaves.
3. Persist `MIG-003` decomposition run and sufficiency requirements.
4. Return a manifest-backed `question-decomposition.json`.
5. Update the live stage handler to consume the Decomposer output manifest instead of `build_fixture_qdt_candidate()`.
6. Add a fresh-route Decomposer canary that does not rely on `--decomposer-runtime-transport-response` when policy requires external model reachability.
7. Make QDT persistence migrations upgrade-safe against live-shaped DB clones before relying on true-production canaries for release evidence.
8. Persist and report whether QDT leaves consumed AMRG hints or produced anchor dependency requests.
9. Add a no-workaround live-shaped clone migration proof:
   - start from a clone of the current live DB,
   - do not reset or manually rebuild QDT tables,
   - run the true-production decomposition stage,
   - verify `qdt_decomposition_runs`, required questions, sufficiency requirements, and anchor slices have the expected compatibility columns and indexes.

Acceptance:

- Fixture question produces question-specific leaves, not the generic source/direct/mechanics template.
- QDT still rejects probability/fair value/SCAE outputs.
- Handoff report shows Decomposer model execution provenance with `gpt-5.5-high`.
- The Decomposer phase can distinguish question-specific live-route output from transport-response contract proof.
- A live-shaped DB clone can pass the Decomposer persistence path without clone-only table reset or schema surgery.

### Phase 5 - Wire AMRG Into Real Decomposition

Goal: make AMRG useful to the Decomposer without giving it forecast authority.

2026-06-27 audit status: AMRG context artifacts and operator reporting exist, and the final audited Decomposer QDT consumed deterministic AMRG relationship hints while preserving AMRG as non-authoritative context. This phase is still partially implemented because question-specific anchor dependency requests remain unproven.

Modify existing surfaces:

- `orchestrator/scripts/predquant/amrg.py`
- `orchestrator/scripts/bin/build_related_live_market_context.py`
- Decomposer QDT prompt/builders.
- `decomposer/scripts/ads_decomposer/qdt.py`

Tasks:

1. Feed AMRG candidates and relationship edges into the Decomposer prompt through a fixed `amrg-decomposer-context/v1` prompt section as context hints only.
2. Preserve weak-context-only limits:
   - weak AMRG can suggest relevant context leaves or retrieval hints,
   - it cannot select QDT,
   - it cannot repair QDT,
   - it cannot author prior anchors.
3. Include at most 12 AMRG hints per case:
   - up to 5 deterministic relationship hints,
   - up to 5 vector-neighbor weak-context hints,
   - up to 2 strict-precedence anchor candidates.
4. Each hint must include hint ref, source market ref, relation type, effect status, allowed use, prohibited use, freshness/refresh status, and candidate leaf relevance.
5. Let Decomposer use AMRG hints only to generate context leaves, retrieval hints, or conditional anchor dependency requests.
6. Let Decomposer request anchor dependency contracts only when the question genuinely needs upstream/conditional market structure.
7. Validate requested anchor contracts against AMRG strict-precedence constraints.
8. Add operator metadata showing which AMRG hints were considered and which QDT leaves reference them.
9. Add a canary fixture/case where AMRG provides at least one useful deterministic retrieval hint and the Decomposer either:
   - references it in a leaf/retrieval hint with allowed-use metadata,
   - or explicitly records why it was ignored.
10. Require strict-precedence anchor requests to carry the validated AMRG anchor ref and downgrade/block when refresh or precedence validation is stale.
11. Add negative tests proving AMRG cannot alter QDT selection, repair QDTs, emit SCAE deltas, or provide probability anchors without strict-precedence validation.

Acceptance:

- Generic context candidates influence prompt context only.
- QDT anchor dependency contracts are only accepted after deterministic AMRG validation.
- AMRG remains non-authoritative for probability, QDT selection, and SCAE deltas.
- Operator reports can show per-hint Decomposer consumption status for true-production runs, not only AMRG candidate availability.

### Phase 6 - Activate AMRG Vector And Advisory Assist Paths

Goal: turn AMRG optional components from contract-only into bounded runtime contributors.

2026-06-27 audit status: the vector runtime path is present and the true-production clone canary built descriptors and persisted unavailable diagnostics. The local Ollama route was unavailable, model assist was `not_requested`, and the final audited QDT consumed deterministic AMRG hints. Treat this phase as partially implemented and operationally incomplete until vector readiness and assist policy are explicitly resolved.

Modify existing surfaces:

- `orchestrator/scripts/predquant/amrg.py`
- `orchestrator/scripts/bin/build_related_live_market_context.py`
- production handler AMRG stage.
- tests in `test_amrg_context.py` and `test_amrg_vector.py`.

Tasks:

1. Add an Ollama-backed AMRG embedding preflight:
   - resolve `amrg_vector_embedding` from `orchestrator/plans/autonomous-decomposition-swarm-model-lane-policy.json`,
   - require provider `ollama`, route `ollama/local`, and configured model `BAAI/bge-base-en-v1.5`,
   - check `OLLAMA_HOST` or default to `http://localhost:11434`,
   - verify Ollama is reachable with `GET /api/version`,
   - verify the model is available with `POST /api/show`,
   - if missing and downloads are allowed for this environment, download through the documented Ollama path:

     ```bash
     ollama pull BAAI/bge-base-en-v1.5
     ```

     or the equivalent API call:

     ```bash
     curl -X POST http://localhost:11434/api/pull \
       -H "Content-Type: application/json" \
       -d '{"model":"BAAI/bge-base-en-v1.5","stream":false}'
     ```

   - if the configured BGE model name does not resolve in the local Ollama installation, record `amrg_vector_candidate_source_unavailable` rather than silently switching models; any change to an Ollama-native fallback such as `all-minilm`, `mxbai-embed-large`, or `nomic-embed-text` must update the model-lane policy and tests in the same implementation slice.
2. Wire AMRG embedding calls to Ollama's current embeddings API:
   - use `POST /api/embed`, not the superseded `/api/embeddings`,
   - send a single descriptor or batch of active-safe descriptor strings as `input`,
   - set `model` to the resolved model-lane id,
   - set `truncate=false` for preflight smoke tests so context overflow fails visibly,
   - set `keep_alive` explicitly when the runtime wants the model to stay warm for the batch,
   - parse `embeddings` from the response and validate that each vector is numeric, finite, non-empty, and matches the configured AMRG dimension before writing a ready snapshot.

   Smoke-test request:

   ```bash
   curl -X POST http://localhost:11434/api/embed \
     -H "Content-Type: application/json" \
     -d '{"model":"BAAI/bge-base-en-v1.5","input":"AMRG embedding smoke test","truncate":false}'
   ```

   Batch request shape for descriptor indexing:

   ```bash
   curl -X POST http://localhost:11434/api/embed \
     -H "Content-Type: application/json" \
     -d '{"model":"BAAI/bge-base-en-v1.5","input":["descriptor one","descriptor two"],"truncate":false,"keep_alive":"5m"}'
   ```

3. Add a live AMRG vector build path:
   - build active-safe descriptors for selected and candidate markets,
   - call the local Ollama BGE embedding route through the preflighted `/api/embed` client when available,
   - create vector index snapshot,
   - generate capped vector-neighbor candidates,
   - fall back to non-blocking unavailable diagnostics.
4. Persist Ollama vector provenance:
   - provider, route id, resolved model id, download command contract,
   - Ollama base URL with host redacted if needed,
   - Ollama version,
   - model digest or `POST /api/show` digest-equivalent metadata when available,
   - embedding dimension, descriptor schema, descriptor hashes, source cutoff timestamp,
   - index snapshot id and cosine metric.
5. Add optional model-assist invocation:
   - send only existing candidate refs and compact metadata,
   - validate output with existing forbidden-output scanner,
   - persist provenance,
   - keep model-only candidates weak context.
   - wire an OpenClaw OAuth assist transport or require run policy to record `model_assist_status=not_requested` as an explicit optional choice.
   - add a canary assertion that model assist is either invoked successfully, explicitly unavailable, or explicitly disabled by policy.
6. Wire `amrg-refresh-policy/v1` into live AMRG and persist the effective policy with every AMRG context artifact:
   - market exposure/price/context descriptor TTL: 1 hour,
   - weak relationship context TTL: 24 hours,
   - vector index snapshot TTL: 24 hours,
   - strict-precedence anchor validation TTL: 6 hours,
   - model-assist classification TTL: 24 hours.
7. Apply refresh/downgrade behavior:
   - stale weak context may remain a prompt hint only if marked stale,
   - stale deterministic/strict effects must downgrade to weak context or block anchor use until refreshed,
   - refresh failure records degraded/unavailable status and reason,
   - promoted effects must never be silently reused after refresh failure.
8. Add an AMRG operator report:
   - candidate count/source mix,
   - vector status,
   - Ollama route/model/preflight status,
   - whether the model had to be pulled for this run,
   - embedding dimensions and descriptor count,
   - model-assist status,
   - relationship statuses,
   - refresh/downgrade reasons,
   - strict-precedence anchor validation state,
   - whether the Decomposer consumed each AMRG hint.
9. Add an operator preflight for the local Ollama route:
   - checks service reachability,
   - checks configured model availability,
   - reports pull allowance,
   - runs one dimension-valid smoke embed when the route is expected to be ready,
   - emits the same status vocabulary used by AMRG artifacts and real-runtime canary reports.

Acceptance:

- Vector unavailable does not block QDT/research.
- Vector available means Ollama `/api/embed` successfully returned dimension-valid embeddings for active-safe descriptors and AMRG produced weak-context vector-neighbor candidates.
- Missing Ollama service, missing model, failed `ollama pull`, failed `/api/embed`, wrong dimensions, or non-finite vectors all produce explicit unavailable/degraded diagnostics and do not block deterministic AMRG.
- Model assist cannot promote edges or author probabilities.
- AMRG report identifies whether the real Decomposer consumed AMRG hints.
- If vector or assist is optional for a run, the operator report and readiness output say so explicitly; an accidental unavailable/not-requested state must not look like a ready vector/assist lane.

### Phase 7 - Implement Real Retrieval And Sufficiency

Goal: replace structured-market-metadata certification with actual retrieval evidence and high-certainty sufficiency certificates.

2026-06-27 audit status: this is the current hard blocker. The retrieval materializer can build deterministic packets from supplied candidates, but the true-production handler currently invokes it with no fetched candidates, no search candidate URLs, and no native candidates. That correctly blocks Researcher execution with `retrieval_sufficiency_not_certified`.

Modify existing surfaces:

- `researcher-swarm/scripts/bin/build_retrieval_packet.py`
- `researcher-swarm/scripts/bin/run_browser_retrieval.py`
- `researcher-swarm/scripts/bin/run_native_gpt_research.py`
- `researcher-swarm/scripts/researcher_swarm/retrieval.py`
- `researcher-swarm/scripts/researcher_swarm/browser_provider.py`
- `researcher-swarm/scripts/researcher_swarm/native_research.py`
- `researcher-swarm/scripts/researcher_swarm/metadata_resolver.py`

Tasks:

1. For each QDT leaf, construct queries from the leaf text, required evidence fields, source classes, and AMRG retrieval hints.
2. Replace the true-production handler's empty-candidate retrieval call with a real candidate acquisition step:
   - direct URLs from market metadata, rules, resolution source, source registry, and AMRG retrieval hints,
   - provider search results when no direct source is enough,
   - OpenClaw/web fetch extraction for known URLs,
   - native GPT candidate discovery only as candidate URL discovery.
3. Persist every source access attempt, including no-candidate, provider-unavailable, fetch-failed, admitted, rejected, duplicate, stale, and insufficient statuses.
4. Capture direct official/resolution URLs first.
5. Add a concrete browser/search provider adapter behind `researcher_swarm.browser_provider`.
6. Treat `openclaw.web_fetch` as URL fetch/extraction only; it must not be treated as search.
7. Add `search-candidate-url/v1` with query variant id, query role, rank, URL, title/snippet hashes, provider id, searched-at timestamp, and result source.
8. Use this fallback order:
   - direct URLs from market/rules/evidence/AMRG/registry,
   - structured feeds and curated source registry,
   - configured browser/search provider,
   - native GPT candidate discovery,
   - targeted expansion.
9. Enforce search rank caps:
   - primary query: top 10 URLs per query variant,
   - contradiction query: top 6 URLs,
   - negative-check query: top 5 URLs per required check.
10. Use GPT 5.5 high native research as candidate discovery, not final source metadata authority.
11. Add `native-research-candidate-discovery/v1`:
   - critical/source-of-truth: max 12 candidate URLs,
   - high/direct/catalyst: max 8 candidate URLs,
   - normal: max 5 candidate URLs,
   - mechanics/rules-only: max 4 candidate URLs.
12. Native research output must include URL, source label, why it may matter, related leaf id, candidate claim text, and uncertainty notes.
13. Native research output must not include source-family final authority, claim-family final authority, temporal safety final authority, sufficiency certification, probability, fair value, SCAE delta, or decision recommendation.
14. Fetch every native-research URL and deterministically admit or reject it before classification can use it.
15. Provide leaf subagents with scoped retrieval budgets and allowed transports for follow-up research from assigned evidence.
16. Resolve source class/family, claim family, temporal safety, breadth, contradiction, negative checks, and missingness deterministically for both pre-dispatch evidence and subagent-discovered supplemental evidence.
17. Require `RET-008` sufficiency certificate or structural unanswerability proof before classification dispatch; after subagent follow-up research, require an updated sufficiency/reconciliation artifact before verification/SCAE.
18. Add a clone canary that reaches at least one source-populated high-certainty retrieval certificate before Researcher dispatch.

Acceptance:

- A thin retrieval case blocks classification instead of certifying from metadata.
- A sufficient retrieval case produces admitted evidence items, chunk/span refs, breadth coverage, and sufficiency certificate refs.
- Leaf-discovered supplemental evidence is admitted only after deterministic metadata/temporal/sufficiency validation.
- Native GPT research unavailability is diagnostic unless all other transports fail sufficiency.
- Tests prove direct URL priority, no-search `web_fetch` behavior, rank cap enforcement, dedupe, fallback diagnostics, native candidate caps, and forbidden native research fields.
- A true-production canary no longer blocks solely because no retrieval candidates were supplied.

### Phase 8 - Implement Real Researcher Swarm Execution

Goal: run GPT 5.5 high leaf researchers under strict isolation and sidecar schemas.

2026-06-27 audit status: the OpenClaw runtime adapter, model-execution evidence checks, and leaf barrier contracts are present, but the end-to-end path is blocked before researcher dispatch. A strict clone canary with `--require-researcher-model-executed` currently fails with `researcher_model_runtime_not_verified`.

Modify existing surfaces:

- `researcher-swarm/scripts/bin/run_researcher_swarm.py`
- `researcher-swarm/scripts/bin/spawn_leaf_researchers.py`
- `researcher-swarm/scripts/bin/validate_researcher_sidecars.py`
- `researcher-swarm/scripts/researcher_swarm/model_context.py`
- `researcher-swarm/scripts/researcher_swarm/assignments.py`
- `researcher-swarm/scripts/researcher_swarm/classification.py`
- `researcher-swarm/scripts/researcher_swarm/classification_matrix.py`
- `researcher-swarm/scripts/researcher_swarm/isolation.py`
- `researcher-swarm/scripts/researcher_swarm/subagents.py`
- `researcher-swarm/scripts/researcher_swarm/persistence.py`

Tasks:

1. Allow validated `model_executed` researcher contexts in addition to current metadata-only context.
2. Build compact assignment packets per leaf using artifact refs, allowed evidence refs, follow-up research budgets, allowed transports, and explicit forbidden context refs.
3. Launch isolated researcher runs with GPT 5.5 high through the control-plane subagent adapter from Phase 2.
4. Let each leaf subagent perform bounded leaf-scoped research from its assigned evidence when needed.
5. Validate sidecars:
   - direction labels: `supports_yes`, `supports_no`, `mixed`, `neutral`, `irrelevant`, `insufficient`,
   - strength labels: `strong`, `moderate`, `weak`, `none`,
   - confidence labels: `high`, `medium`, `low`,
   - quality labels: `high`, `medium`, `low`, `unusable`,
   - evidence ids reviewed,
   - supplemental evidence ids proposed,
   - condition scope,
   - no probability/fair-value/forecast fields.
6. Enforce sidecar acceptance rules:
   - `high` or `medium` confidence plus `high` or `medium` quality can pass to verification,
   - `low` confidence, `low` quality, `unusable`, missing evidence refs, or unsupported claims block or downgrade to non-scoreable,
   - `mixed`/contradictory classifications must carry both supporting and opposing admitted evidence refs,
   - `irrelevant`/`insufficient` cannot contribute to SCAE evidence deltas,
   - sidecars must reference admitted evidence ids only, except for explicitly proposed supplemental evidence refs.
7. Route any supplemental evidence through deterministic metadata, temporal, breadth, and sufficiency validation before it can affect coverage or SCAE readiness.
8. Persist assignments, isolation audits, classifications, supplemental evidence refs, coverage proofs, escalation decisions, and reconciliation.
9. Build and persist the leaf-research barrier artifact before verification/SCAE starts.
10. Keep Orchestrator as the state machine; Researcher Swarm should not select global next work or write forecasts.
11. Require runtime bundles to contain real sidecar refs, classification refs, isolation audit refs, and model-executed provenance before they can satisfy true-production readiness.
12. Add an end-to-end clone canary that passes `--require-researcher-model-executed` after Phase 7 retrieval sufficiency is live.

Acceptance:

- Each leaf has a valid assignment and either accepted classification coverage or a blocker.
- Leaf-scoped follow-up research can enrich evidence for that same leaf without exposing sibling/aggregate context.
- Sibling/aggregate/SCAE/replay/outcome context is absent from leaf researcher inputs.
- The pipeline does not advance past researcher classification while any dispatchable leaf is active, missing, timed out, contaminated, or unclassified.
- True-production leaf subagent results are rejected unless runtime provenance shows `model_executed` with resolved model `openai/gpt-5.5-high`.
- Any researcher probability attempt fails closed.
- A `researcher-classification-readiness-block` artifact is accepted only as an explicit non-scoreable blocker, never as proof of researcher execution.

### Phase 9 - Implement Verification-To-SCAE Evidence Mapping

Goal: feed real verified researcher classifications into SCAE without weakening SCAE authority.

2026-06-27 audit status: SCAE remains healthy, but true runtime classification intake is incomplete. The runtime-bundle-ready path must consume accepted sidecars and verification artifacts, not reuse pilot-style certified reconciliation rows over the retrieval packet.

Modify existing surfaces:

- `researcher-swarm/scripts/researcher_swarm/verification.py`
- `researcher-swarm/scripts/bin/verify_evidence_directionality.py`
- `researcher-swarm/scripts/bin/verify_evidence_quality.py`
- `researcher-swarm/scripts/bin/reconcile_research_sufficiency.py`
- `researcher-swarm/scripts/bin/validate_scae_readiness.py`
- `SCAE/scripts/bin/build_scae_evidence_delta_candidates.py`
- `SCAE/scripts/scae/evidence.py`
- `SCAE/scripts/scae/ledger.py`
- production handler SCAE stage.

Tasks:

1. Verify all non-neutral classifications for direction and evidence quality.
2. Reconcile leaf coverage and sufficiency.
3. Build `scae-evidence-delta-candidate/v1` from accepted classification matrix rows.
4. Replace any runtime-bundle-ready shortcut that calls pilot-style `_certified_reconciliation_rows(qdt, retrieval_packet, verification_ref)` with a path that reads:
   - runtime bundle refs,
   - accepted sidecar refs,
   - classification matrix rows,
   - isolation audit refs,
   - direction verification refs,
   - quality verification refs,
   - sufficiency reconciliation refs.
5. Persist a SCAE evidence delta bundle ref and require it in true-production readiness/canary output.
6. Apply initial deterministic direction mapping:
   - `supports_yes` -> positive sign,
   - `supports_no` -> negative sign,
   - `mixed` -> branch/netting candidate, not a direct single delta,
   - `neutral`, `irrelevant`, `insufficient` -> no delta.
7. Apply initial uncapped log-odds tiers before SCAE caps/netting:
   - strong: 0.35,
   - moderate: 0.20,
   - weak: 0.08,
   - none: 0.
8. Apply discounts:
   - confidence high 1.0, medium 0.6, low 0.0,
   - quality high 1.0, medium 0.7, low/unusable 0.0.
9. Apply dependence/netting rules before ledger input:
   - deltas sharing a claim family or source family are netted/capped,
   - contradictory family pairs are carried as opposing candidates,
   - SCAE remains final numeric authority and may further cap, discount, drop, or mark watch-only.
10. Reject missing/low-certainty/unverified inputs or downgrade to non-scoreable/watch-only.
11. Run deterministic SCAE ledger.
12. Persist only SCAE `production_forecast_prob`.

Acceptance:

- SCAE ledger references real classification/verification artifacts.
- Non-SCAE model outputs never author numeric probabilities.
- Invalid or thin evidence does not produce scoreable forecasts.
- Real-runtime canary requires non-empty SCAE evidence delta refs before a run can be considered true-scoreable-ready.

### Phase 10 - Replace Production-Pilot Handler With True Production Handler

Goal: create the real production handler factory using existing runner extension points.

2026-06-27 audit status: the true-production handler factory exists and runs a bounded non-scoreable clone canary. It is not scoreable-ready because retrieval candidate acquisition is empty, researcher execution is blocked, and verification-to-SCAE mapping still needs real runtime artifact intake. The live-shaped clone audit also exposed QDT persistence compatibility as a release gate for this handler path.

Modify existing surfaces:

- Prefer a new module:
  - `orchestrator/scripts/predquant/ads_production_handlers.py`
- Reuse helpers from:
  - `ads_production_readiness_handlers.py`,
  - `ads_handoff_resolver.py`,
  - `ads_operational_canary.py`,
  - `ads_live_readiness.py`.

Tasks:

1. Build stage handlers for the current `ADS_PIPELINE_STAGE_ORDER`.
2. For early stages, reuse current case/evidence/profile/AMRG materializers.
3. For decomposition/retrieval/researcher/SCAE, invoke the real runtime entrypoints from Phases 4, 7, 8, and 9.
4. Remove the empty-candidate retrieval invocation from the true-production path once Phase 7 lands.
5. Remove any runtime-bundle-ready verification shortcut that bypasses accepted sidecars and verification artifacts once Phase 9 lands.
6. Keep strict manifest handoffs required.
7. Keep scoreable writes in decision stage only.
8. Make handler metadata distinguish:
   - pilot fixture,
   - production readiness non-scoreable,
   - true production specialist runtime.
9. Add `ads-production-stage-failure-policy/v1` with failure classes:
   - `retryable_transport`,
   - `retryable_model_transport`,
   - `invalid_artifact_terminal`,
   - `thin_evidence_watch_only`,
   - `policy_violation_quarantine`,
   - `fatal_operational`.
10. Apply retry/failure behavior:
   - transport/model transport: at most 1 retry,
   - deterministic validation failure: no retry unless a bounded repair path is explicitly defined,
   - policy violation/contamination/forbidden output: quarantine and block scoreable persistence.
11. Every failure must write stage status, error event, safe reason code, replay command/ref, lease release/drain action, and pipeline disable/continue decision.
12. Decision stage remains the only scoreable write surface; failed upstream stages cannot write predictions.
13. Before using this handler as cutover evidence, run it on a live-shaped clone without QDT table reset or manual schema surgery.

Acceptance:

- `run_ads_one_case_canary.py --handler-factory predquant.ads_production_handlers` runs on a clone and produces real QDT/research/SCAE artifacts.
- Handoff report shows all stage output manifests valid and no unresolved refs.
- True-live readiness accepts the production handler and rejects pilot/readiness handlers.
- Acceptance requires a canary with both QDT and Researcher model-executed evidence, not only a non-scoreable skeleton run.
- The handler can run against a live-shaped clone without a decomposition persistence migration failure.

### Phase 11 - Canary Ladder With Real Specialist Runtime

Goal: prove the real v2 intelligence path without jumping to unattended operations.

2026-06-27 audit status: the real-runtime canary report exists and caught the current gap. It passes the non-scoreable skeleton run only when researcher execution is not required, and fails with `researcher_model_runtime_not_verified` when strict researcher evidence is required. The canary ladder must also catch live-shaped DB migration failures before they reach live operations.

Tasks:

1. Clone DB one-case non-scoreable run.
2. Clone DB one-case scoreable calibration-debt run.
3. Clone DB two-case bounded run.
4. Live DB non-executing/preflight.
5. Live DB one-case scoreable calibration-debt run.
6. Live DB two-case bounded run.
7. Run handoff reports and AMRG reports after each run.
8. Run storage and scoring/calibration reports.
9. Disable pipeline after each run.
10. Enforce `ads-real-runtime-canary-criteria/v1`:
    - active runs = 0,
    - active leases = 0,
    - unresolved manifest refs = 0,
    - stage error events = 0 except explicitly expected failure-injection tests,
    - pipeline disabled or stopped according to run policy,
    - handoff report `ok=true`,
    - QDT model-executed evidence present for `gpt-5.5-high`,
    - retrieval sufficiency certified or structural unanswerability proven,
    - Researcher model-executed evidence present for `gpt-5.5-high` when the canary claims true runtime readiness,
    - SCAE evidence delta refs present before any scoreable prediction is allowed.
11. Enforce prediction deltas:
    - one-case scoreable canary writes forecast decision records +1,
    - market predictions +1 only if SCAE validity is scoreable,
    - otherwise market predictions +0 with watch-only/non-scoreable reason,
    - two-case bounded canary applies the same expectation per case with no duplicate prediction for the same market/case.
12. Enforce resource gates:
    - DB WAL growth warning above 512 MB,
    - DB WAL growth block above 2 GB,
    - single case wall time warning above 30 minutes,
    - block above 60 minutes unless explicitly running a failure-injection test.
13. Add a migration-compatibility rung before any live DB execution:
    - clone current live DB,
    - run without QDT table reset/workaround,
    - fail the ladder on missing compatibility columns/indexes or migration-order exceptions,
    - record the migration proof artifact in the canary report.

Acceptance:

- No active runs/leases after any run.
- QDTs are question-specific and model-executed by GPT 5.5 high.
- Research sidecars are model-executed by GPT 5.5 high.
- Retrieval is source-populated and sufficiency-certified before researcher dispatch.
- AMRG vector/assist status is explicit and policy-compatible.
- SCAE is the only numeric authority.
- Scoreable predictions are written only when sufficiency/verification passes.
- Live-shaped clone compatibility passes before live execution rungs are allowed.

### Phase 12 - Observability And Operator Review

Goal: make live operation inspectable before expansion.

2026-06-27 audit status: handoff, AMRG, health, storage, calibration, and real-runtime reports exist. True readiness still needs to derive positive evidence from the latest manifests/canary report rather than optional caller-supplied placeholders. The latest read-only readiness check counted a placeholder SCAE delta ref, and storage maintenance reported `apply_required=true`; both should be explicit operator signals.

Modify existing surfaces:

- `report_ads_handoffs.py`
- new or extended AMRG report CLI.
- `check_ads_live_readiness.py`
- `check_pipeline_health.py`
- storage/scoring CLIs.

Tasks:

1. Add one operator report that summarizes per run:
   - case,
   - QDT model provenance,
   - QDT specificity checks,
   - AMRG consumed hints,
   - retrieval sufficiency,
   - researcher model provenance,
   - verification/SCAE readiness,
   - final SCAE probability and interval,
   - prediction baseline,
   - trace/replay refs,
   - blockers.
2. Add readiness issues for:
   - deterministic QDT in true-production mode,
   - metadata-only researcher in true-production mode,
   - missing AMRG refresh status for promoted effects,
   - missing SCAE evidence delta refs,
   - stale storage maintenance plan.
3. In true-scoreable readiness, derive the QDT, retrieval, researcher, AMRG, and SCAE signals from the latest relevant run manifests and real-runtime canary report:
   - reject placeholder SCAE delta refs,
   - reject missing researcher runtime bundle refs,
   - reject retrieval packets with no admitted source evidence unless structural unanswerability is explicitly proven,
   - reject AMRG promoted effects without fresh/compatible refresh status,
   - reject Decomposer runtime evidence that only proves a transport-response fixture when fresh live transport is required by policy.
4. Add alert severities: `blocker`, `warning`, and `info`.
5. Add blocker thresholds:
   - active lease older than 60 minutes,
   - active run older than 90 minutes,
   - stale intake/snapshot above policy threshold,
   - stale resolution sync above policy threshold,
   - unresolved manifest refs,
   - true-production deterministic QDT,
   - metadata-only researcher in true-production mode,
   - non-SCAE probability authority,
   - DB WAL above 2 GB.
6. Add warning thresholds:
   - DB WAL above 512 MB,
   - storage maintenance overdue,
   - AMRG vector unavailable,
   - AMRG weak-context-only,
   - native research unavailable but browser retrieval sufficient,
   - source freshness barely passes.
7. Operator report must show blocker/warning counts, exact run/case refs, remediation command/ref, and whether scheduler may continue.
8. Surface the live read-only audit state in operator output:
   - active runs/leases,
   - pipeline enabled/disabled state,
   - storage maintenance `apply_required`,
   - count of placeholder/CLI-supplied readiness refs,
   - latest real-runtime canary evidence source.

Acceptance:

- Operator can tell whether a run was pilot, readiness, or true production.
- Operator can trace every scoreable prediction back to QDT, retrieval, researcher, verification, SCAE, decision, and replay manifests.
- Operator can see when readiness was blocked only by CAL-001 while other positive-evidence checks were supplied by placeholders or CLI overrides.

### Phase 13 - CAL-001 Evidence Accumulation And Production Expansion

Goal: move from bounded calibration-debt canaries to controlled production only after empirical evidence exists.

2026-06-27 audit status: CAL-001 remains blocked. The live DB has 7 ADS predictions, 8 forecast decision records, 0 scored ADS predictions, 0 scorecards, and no first-100 trace completeness evidence, tail/regime/protected-component diagnostics, or pointer-stability evidence. Expansion must wait for real-runtime, non-pilot scoreable predictions that resolve and score; pilot predictions and non-scoreable clone decisions cannot clear this gate.

Tasks:

1. Keep continuous scoreable production blocked until CAL-001 passes.
2. Allow only bounded scoreable canaries under explicit calibration-debt controls.
3. As markets resolve:
   - run scoring,
   - generate Brier reports,
   - write scorecards,
   - verify first-100 trace completeness,
   - build tail/regime/protected-component diagnostics,
   - evaluate pointer stability.
4. Only after CAL-001 clears:
   - stage 1: max 5 scoreable cases/day for 7 days,
   - stage 2: max 10/day for 14 days if reports are clean,
   - stage 3: max 25/day after explicit operator review.
5. Roll back or block expansion on:
   - any non-SCAE probability write,
   - missing trace/replay for a scoreable prediction,
   - unresolved manifest ref,
   - two consecutive stage-failure runs,
   - rolling scored Brier worse than market baseline by 0.05 or more after at least 20 newly scored predictions,
   - calibration diagnostics fail tail/regime/protected-component guardrails.
6. Persist expansion decisions as operator policy artifacts with reviewed scorecard refs.
7. Split calibration evidence by lane:
   - pilot/fixture predictions,
   - true-production non-scoreable decisions,
   - true-production scoreable predictions.
8. Count only true-production scoreable predictions with full QDT, retrieval, researcher, verification, SCAE, decision, training-trace, and replay refs toward CAL-001 clearance.
9. Require scorecards to carry runtime evidence refs so a scored prediction cannot clear calibration debt if it lacks true v2 intelligence provenance.

Acceptance:

- CAL-001 gates pass with real scored evidence.
- Scheduler true-live gate allows production handler without calibration-debt canary bypass.
- Continuous operation remains bounded by stop/disable policy and monitoring.
- CAL-001 reports make clear that pilot/scaffolding predictions are excluded from true-production expansion evidence.

## Concrete First Implementation Slice

The smallest high-value implementation slice is:

1. A no-workaround live-shaped clone proof for QDT persistence compatibility:
   - clone the current live DB,
   - run the true-production Decomposer persistence path,
   - verify the `qdt_artifact_id` compatibility issue is resolved without table reset or manual schema surgery.
2. Phase 7 retrieval transport wiring in the true-production handler:
   - direct source URLs,
   - configured search/provider candidates,
   - URL fetch/extraction,
   - native GPT candidate discovery as URL discovery only,
   - persisted admitted/rejected source attempts.
3. A clone canary proving at least one source-populated retrieval packet reaches `RET-008` sufficiency or a structural unanswerability proof.
4. Phase 8 Researcher Swarm dispatch on that certified retrieval packet, with a strict canary passing `--require-researcher-model-executed`.
5. Phase 9 verification-to-SCAE evidence delta mapping from accepted sidecars/classification verification artifacts.
6. Phase 12 true-readiness hardening so the gate derives positive evidence from manifests/canary reports and rejects placeholders.
7. AMRG operational polish in parallel only where it does not delay Phase 7:
   - Ollama preflight/reporting,
   - explicit model-assist policy,
   - Decomposer hint-consumption proof.

This slice fixes the current blockers shown by the 2026-06-27 audits: QDT runtime plumbing can run but needs live-shaped migration proof, and retrieval is not yet producing certified source evidence, so Researcher and SCAE cannot prove the real v2 intelligence path.

## Non-Goals

- Do not create a second pipeline runner.
- Do not move live control-plane ownership out of Orchestrator.
- Do not let Decomposer, Researcher, AMRG, or model assist author probabilities.
- Do not loosen CAL-001 for continuous production.
- Do not bypass strict manifests for convenience.
- Do not replace AMRG; extend its current active-safe/vector/anchor/refresh architecture.
- Do not treat CLI placeholder refs, pilot predictions, or clone-only schema workarounds as production-readiness evidence.
