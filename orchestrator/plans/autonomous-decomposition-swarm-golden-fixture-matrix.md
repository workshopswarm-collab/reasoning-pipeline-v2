# Autonomous Decomposition-Swarm Golden Fixture Matrix

Purpose: define the fixture suite required before runtime integration and later cutover. Session 1 owns the harness and registry. Sessions 2-6 own expected artifacts and validations for their components.

Status values: `not_started`, `fixture_defined`, `implemented`, `passing`, `waived`

## Fixture Matrix

| Fixture ID | Stage Gate | Owner Sessions | Scenario | Required Assertions | Status |
| --- | --- | --- | --- | --- | --- |
| FIX-001 | Wave B | 1-5 | Minimal standalone binary market | Full fixture path reaches decision context; no live execution; trace pointer written. | implemented |
| FIX-002 | Wave B | 1,2,5 | Family-aware binary child | Selected child remains binary; family context persists; sibling prices never become evidence deltas. | implemented |
| FIX-003 | Wave B | 1,2,3 | AMRG no-related-context waiver | Empty active-safe candidate pool writes explicit waiver and decomposition proceeds. | implemented |
| FIX-004 | Wave B | 1,2,3 | AMRG weak-context artifact | Weak semantic/shared-driver edge can inform decomposition/retrieval hints but cannot promote effects. | implemented |
| FIX-005 | Wave B | 1,2,3,5 | Conditional-anchor negative | Strict-precedence candidate fails validation; QDT fallback/repair/exhaustion policy is followed. | implemented |
| FIX-006 | Wave B | 1,4,5 | Researcher probability-authoring attempt | Sidecar/schema rejects probability, fair value, interval, reassembly, and decision recommendation fields. | implemented |
| FIX-007 | Wave B | 1,5 | Decision override attempt | Decision cannot replace probability or upgrade SCAE validity. | implemented |
| FIX-031 | Wave B | 1,3,4,5 | Canonical machine-template enforcement | QDT and researcher outputs must be schema-bound machine artifacts with prompt hashes, schema versions, stable IDs, and no prose-only substitutes. | passing |
| FIX-032 | Wave B | 1,3,4 | Thin leaf retrieval expands before research | Initial retrieval misses required source/value/negative-check coverage; targeted expansion runs until a high-certainty sufficiency certificate is produced before researcher dispatch. | passing |
| FIX-042 | Wave B | 1,4 | Compact leaf research assignment | `leaf-research-assignment/v1` contains stable refs, hashes, requirement IDs, evidence refs, prompt/model metadata, output refs, and budget caps; it rejects embedded evidence bodies, duplicated full QDT leaves, narrative research reports, and probability-bearing fields. | passing |
| FIX-044 | Wave B | 1,4 | Researcher context isolation | Two leaf researchers in one case receive fresh isolated contexts; peer sidecars, sibling assignments, aggregate summaries, SCAE refs, replay/scoring refs, and outcome refs are absent; a contaminated packet blocks subagent launch. | passing |
| FIX-045 | Wave B | 1,3 | Retrieval breadth dimensions | Browser retrieval returns many URLs, but they collapse to one same-claim family and one syndicated source family; span-bound atomic claim candidates are validated, normalized, and hashed into claim-family resolutions; breadth validation rejects certification until independent source-class, claim-family, source-family, freshness, contradiction-search, negative-check, and protected-primary requirements are satisfied or structurally unanswerable. Browser transport is recorded but never counted as a source family. | passing |
| FIX-046 | Wave B | 1,3 | Native research metadata resolver | GPT-5.5 native research returns citation candidates and model-proposed source labels when enabled; deterministic resolver accepts supported official/domain/publisher/claim/timestamp metadata, records unsupported proposals as diagnostics, maps unresolved fields to `unknown_not_counted`, and triggers expansion or sufficiency failure when required breadth cannot be met. Native research unavailable writes diagnostics and does not block browser-only retrieval. | passing |
| FIX-047 | Wave B | 1,2,3 | Small metadata classifier assist | OpenAI OAuth-routed `openai/gpt-5.4-mini` classifier receives compact source-candidate packets when enabled, writes classifier slices, reduces ordinary source-class/claim-family unknowns when validator rules accept the output, rejects unsupported/protected-primary-only/temporal-safety-only/spanless proposals, and records acceptance rates for tuning. Classifier unavailable writes diagnostics and does not block browser-only retrieval. | passing |
| FIX-048 | Wave B | 1,3,4 | Browser-only retrieval cutover | News/feed API transport is absent; `openclaw_web_fetch_browser` provider diagnostics are written; direct official/resolution URLs are captured before broad web search; OpenClaw `web_fetch` / browser retrieval produces temporally eligible `retrieval-evidence/v1` rows with chunk refs, deterministic source metadata, claim-family resolutions, breadth coverage, and sufficiency certificates; Session 4 assignment rendering proceeds without API/feed infrastructure. | passing |
| FIX-043 | Wave B | 1,4,5 | Adaptive researcher escalation | A normal leaf produces one primary assignment; critical/source-of-truth, evidence conflict, low retrieval confidence, low classification confidence, high pre-SCAE leverage proxy, and structural unanswerability triggers create bounded extra assignments, enforce the five-concurrent-researcher cap, and block SCAE-ready reconciliation until required escalations complete. | passing |
| FIX-033 | Wave B | 1,4,5 | Researcher skips certified evidence | Coverage proof/reconciliation rejects a sidecar that classifies a leaf without reviewing assigned evidence refs and required negative checks. | passing |
| FIX-035 | Wave B | 1,2,3 | AMRG vector source unavailable | Ollama route, BGE model, or vector index unavailable writes `amrg_vector_candidate_source_unavailable`; deterministic AMRG candidates or no-related-context waiver still proceed. | passing |
| FIX-037 | Wave B | 1,2,5 | Existing intake to ADS case contract | Real SQLite fixture rows from `markets` and `market_snapshots` produce `ads-case-contract/v1`, artifact manifest, evidence packet input refs, source row IDs, source payload hash, prediction-time market baseline, and stale/lookahead snapshot rejection. | passing |
| FIX-039 | Wave B | 1,3,4,5 | Runtime script placement static scan | Planned script paths resolve to the owning runtime workspace: QDT under Decomposer, retrieval/research/verification under Researcher Swarm, ledger under SCAE, and Orchestrator-only for intake/context/wakeup/handoff/post-SCAE routing. | implemented |
| FIX-040 | Wave B | 1,2,5 | Continuous automation two-case loop | Runner leases a unique eligible case from existing intake rows, completes the vertical slice to scoreable SCAE forecast persistence, releases the lease, selects a second unique case, then honors stop-after-current without duplicate leases or duplicate prediction rows. | passing |
| FIX-041 | Wave B | 1 | Manual pipeline enable switch | `pipeline_enabled=false` blocks runner start and new lease acquisition; enabling permits the next lease; disabling during an active case writes the configured stop-after-current or safe-drain signal and acknowledgement. | passing |
| FIX-008 | Cutover | 2,5 | Stale/illiquid prior | Market prior reliability shrinks toward validated structural/base-rate anchor when present; no instant-snapshot-only shrink. | not_started |
| FIX-009 | Cutover | 2,5 | Fresh/liquid strong prior | Public old evidence receives assimilation discount and does not double count priced information. | not_started |
| FIX-010 | Cutover | 3,5 | Thin retrieval | Retrieval quality lowers leverage, widens interval, and preserves actionability warning. | not_started |
| FIX-011 | Cutover | 3,4,5 | Protected-primary source failure | Source access failure slice persists; critical/source-of-truth leaf cannot use degraded fallback for execution authority. | not_started |
| FIX-012 | Cutover | 4,5 | Contradictory classifications | Direction/quality verification quarantines or excludes ambiguous rows without deadlocking non-critical forecast. | not_started |
| FIX-013 | Cutover | 3,4,5 | Duplicate same-claim evidence | Same claim across leaves contributes once through shared-claim union; no additive duplicate force. | not_started |
| FIX-014 | Cutover | 3,5 | Ambiguous claim equivalence | Uncertain same-claim vs independent-claim defaults conservative, not independent corroboration. | not_started |
| FIX-015 | Cutover | 3,5 | Same-mechanism distinct claims | Same mechanism reduces independence or widens intervals but does not merge as same claim. | not_started |
| FIX-016 | Cutover | 3,5 | Expanded decomposition branch sub-ledger | Effective leaf budget above compact default uses sign-partitioned branch sub-ledgers, not flat summation. | not_started |
| FIX-017 | Cutover | 2,3,5 | AMRG causal cycle downgrade | Concurrent/overlapping/cyclic relation downgrades to diagnostic and cannot create prior anchor. | not_started |
| FIX-018 | Cutover | 2,5 | AMRG adjusted upstream prior reliability | Validated upstream anchor records adjusted upstream probability, reliability context, and source timestamps. | not_started |
| FIX-036 | Cutover | 2,3 | AMRG local vector neighbor | Local Ollama-routed `BAAI/bge-base-en-v1.5` embeds active-safe descriptors, writes an index snapshot and capped neighbor candidates, and vector-only candidates remain weak context unless later validated. | not_started |
| FIX-038 | Cutover | 1,2,5 | SCAE forecast benchmark provenance | SCAE `production_forecast_prob` creates an idempotent `market_predictions` row tied to the case contract prediction-time snapshot; resolution scoring records prediction Brier, market Brier, Brier edge, scoring version, and resolution payload hash. | not_started |
| FIX-019 | Maturity | 2,3,4 | AMRG shared reuse temporal rejection | Cached retrieval/classification reuse is rejected when consuming dispatch temporal provenance is unsafe. | not_started |
| FIX-020 | Cutover | 5 | Structural-prior/base-rate fingerprint overlap | SCAE rejects duplicate structural prior as signed evidence unless distinct fresh not-priced proof exists. | not_started |
| FIX-021 | Cutover | 3,5 | No-catalyst/time-expiration | Missingness and no-catalyst deltas cannot both apply without distinct absence mechanism proof. | not_started |
| FIX-022 | Cutover | 4,5 | Correlated-quality guard | Raw quality multiplier is floored/grouped and final multiplier is recorded before evidence delta. | not_started |
| FIX-023 | Cutover | 5 | Direct-cutover cap stack | Per-update, per-cluster, per-branch, and total caps apply; debt-mode caps are stricter. | not_started |
| FIX-024 | Calibration debt | 5,6 | Calibration-debt hard gates | First-100 trace completeness alone cannot clear debt; resolved/tail/regime/pointer-stability gates are required. | not_started |
| FIX-025 | Cutover | 2,5 | Near-resolution market shrinkage | Near-resolution prior handling distinguishes source-grade contradiction from ordinary uncertainty. | not_started |
| FIX-026 | Cutover | 2,5 | Effective tuning profile selection | Unknown/underpowered domains use global baseline plus conservative overlays; sports/crypto tags remain excluded from initial active profiles. | not_started |
| FIX-027 | Maturity | 6 | Profile canary/rollback | Candidate profile runs in deterministic canary bucket and can roll back by lane-local pointer. | not_started |
| FIX-028 | Maturity | 3,6 | Decomposer-miss learning | Post-resolution decomposer-miss labels feed promoted QDT scoring overlay without leaking same-case outcomes into active dispatch. | not_started |
| FIX-029 | Cutover | 1 | Exact Section 10 operational schema names | Schema name map has no unresolved runtime surface used by live components. | not_started |
| FIX-030 | Cutover | 1 | Structured execution log, error, and replay command | Every failed, blocked, retried, or artifact-validation-failed stage writes `v2_stage_execution_events`, status, safe bounded log refs or explicit no-log reason, error grouping key, replay command, and safe metadata. | not_started |
| FIX-034 | Cutover | 3,4,5 | Insufficient research cannot become clean forecast | Leaf remains uncertified after expansion; SCAE marks forecast invalid or policy watch-only with structural unanswerability proof, never normal high-confidence evidence. | not_started |

## Wave Requirements

- Wave B requires `FIX-001` to `FIX-007` plus `FIX-031` to `FIX-033`, `FIX-035`, `FIX-037`, and `FIX-039` to `FIX-048`.
- Non-executing canary requires all `Cutover` fixtures that apply to the selected canary case class.
- Calibration debt clearance requires `FIX-024` plus resolved replay scorecards.
- Autonomous optimization maturity requires `Maturity` fixtures.

## Completion Checklist

- [x] Fixture registry contains every `FIX-*` row.
- [ ] Each fixture has expected artifacts, expected status transitions, and expected failure modes.
- [x] Each fixture maps to at least one live-cutover blocker or maturity gate.
- [x] Fixture results persist through `golden_fixture_case_results`.
