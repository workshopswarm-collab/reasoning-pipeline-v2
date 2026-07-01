# ADS v2 Source Retrieval And Pipeline Health Remediation Plan

Created: 2026-07-01
Owner: Workbench implementation session
Status: in progress

## Purpose

This plan addresses the issues identified in the latest clone-only ADS v2 end-to-end audit, with
special focus on source search, retrieval, native research, researcher dispatch, AMRG/QDT
handoffs, SCAE authority, reporting, and clone-only safety.

The plan intentionally excludes QMD/LMD and cutover work. It also does not relax CAL/live-readiness
requirements or evidence acceptance thresholds to manufacture a pass.

## Audit Anchor

Fresh audit run:

- Clone path: `/tmp/ads-e2e-fresh-audit-after-qdt-repair.mvDkf9`
- Pipeline run: `ads-pipeline-run:014933b9940a5449d49b216c316ca4b0a8bddd1ed41f33dac76b5071062a0afa`
- Case: `polymarket:1795635`, Bank of Israel July 2026 rate decrease.
- Result: all 13 configured stages completed, active work drained to 0/0, but strict postflight
  failed because retrieval/research was not certified and no scoreable market prediction was written.

Observed issue set:

- Live QDT executed and produced a market-specific decomposition, but required local hardening:
  - MIG-003 persistence falsely rejected `repair_decision` inside schema-repair diagnostics.
  - QDT repair did not synchronize duplicated `leaf_question` and `question_text`.
  - Analyst-consensus leaves could retain stale official-source sufficiency after role repair.
- Source discovery/retrieval is not robust enough:
  - Native research executed, but produced 0 candidate URLs.
  - Native research per-leaf failure diagnostics were too thin.
  - Browser search partially executed, but one provider failure and elapsed-budget exhaustion skipped
    most leaves.
  - Evidence chunks existed, but were too short for classification and claim extraction was not
    attempted.
  - Every leaf remained uncertified because breadth, source-class, claim-family, source-family,
    freshness, and protected-primary requirements were not met.
- Researcher classification was correctly blocked with `retrieval_sufficiency_not_certified`.
- SCAE and decision correctly failed closed:
  - SCAE ledger was `invalid_for_forecast`.
  - execution authority was `forbidden`.
  - no `market_predictions` row was written.
- AMRG was safe but weak:
  - candidate context existed and one edge was consumed by QDT;
  - vector was unavailable but allowed as weak context;
  - model assist was not requested by policy;
  - report fields can show stale `pending_decomposition` state before later evaluated consumption.
- Pipeline reporting can confuse health:
  - every stage can show `stage_completed` while later artifacts are readiness blocks;
  - live QDT call failure can be misread as deterministic/fixture if no accepted QDT exists.
- Clone-only safety needs a stronger guard:
  - preflight should not mutate live control-state metadata unless explicitly allowed.

## Guiding Principle

Do not make downstream gates permissive. Make upstream intelligence and retrieval produce valid,
certified inputs while preserving strict deterministic validators and authority boundaries.

## Strict Sequential Execution Rule

Phases are strict sequential. A session implementing this plan must complete, verify, clean, and
summarize each phase before starting the next one.

If a new bug, mismatch, or blocker appears during a phase:

1. Stop broad implementation.
2. Add a dated note to the current phase or insert a new subphase.
3. Preserve the failing shape as a regression test or clone-only proof.
4. Adjust only the current or next phase unless VM asks for a broader rewrite.
5. Continue only after the updated phase checklist is explicit.

## Cleanup Discipline

Every phase that creates temporary artifacts must use a phase-scoped temp directory:

```bash
TMPDIR="$(mktemp -d /tmp/ads-v2-source-retrieval-phaseN.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT
```

Temporary artifacts include clone DBs, generated JSON reports, copied runtime artifacts, one-off
inspection scripts, generated fixture JSON not intended as durable tests, and canary outputs.

One-off testing scripts must live under the phase temp directory and must be deleted by the trap
after successful testing. Durable regression tests may be committed under repo test directories.

Before completing every phase:

```bash
find /tmp -maxdepth 1 -name 'ads-v2-source-retrieval-phase*' -print
git diff --check
git status --short
```

Success for cleanup means:

- no phase temp directories remain;
- no generated clone DB or canary output is staged;
- no one-off testing script remains outside the temp directory;
- only intentional source, test, and plan changes remain.

## Standing Invariants

- QDT may structure research, but may not forecast, assign probability, create SCAE deltas, or make
  execution decisions.
- QDT repair may fix mechanical schema drift, but must not override semantic blockers or forbidden
  authority leakage.
- AMRG is advisory context only unless a separate policy change explicitly makes assist required.
- Native research may propose candidate URLs and bounded source hints only.
- Browser/search providers may discover source candidates, but deterministic fetch/admission remains
  final authority for evidence.
- Researchers classify bounded certified evidence only; they do not browse freely and do not forecast.
- Verification must emit SCAE-ready deltas before SCAE may produce a valid scoreable forecast.
- SCAE remains the only numeric forecast authority.
- Insufficient cases must write no market prediction.
- Clone-only proof runs stay clone-only unless VM explicitly authorizes live mutation.

## Phase 0 - Baseline, Safety Envelope, And Issue Taxonomy

Status: completed 2026-07-01

Goal: preserve the current failure shape and safety constraints before changing retrieval behavior.

Implementation:

- Reproduce the latest failure on a cloned DB only.
- Add or update compact report taxonomy for:
  - `live_qdt_call_executed_output_rejected`
  - `live_qdt_call_executed_output_accepted`
  - `retrieval_source_populated_but_not_certified`
  - `native_research_executed_no_candidates`
  - `stage_completed_with_readiness_block`
  - `non_scoreable_fail_closed`
- Add a hard guard so live DB preflight cannot write control-state metadata unless an explicit
  `--allow-live-control-state-write` or equivalent flag is supplied.
- Preserve the latest clone-only audit counters as machine-checkable expectations.

Pseudocode:

```python
def assert_clone_only(db_path, allow_live_write=False):
    if is_known_live_db_path(db_path) and not allow_live_write:
        raise SafetyError("live DB mutation requires explicit live-write flag")


def classify_stage_outcome(stage_event, artifact):
    if stage_event["event_type"] == "stage_completed" and artifact["artifact_type"].endswith("_readiness_block"):
        return "stage_completed_with_readiness_block"
    return stage_event["event_status"]


def classify_runtime(report):
    return {
        "qdt": qdt_state(report),
        "retrieval": retrieval_state(report),
        "researcher": researcher_state(report),
        "scae": scae_state(report),
        "decision": decision_state(report),
    }
```

Testing suite:

- Unit tests for live DB guard behavior:
  - live path without explicit flag fails before mutation;
  - clone path proceeds;
  - live path with explicit flag proceeds only in tests using temp DB aliases.
- Unit tests for taxonomy:
  - completed stage plus readiness block reports `stage_completed_with_readiness_block`;
  - live QDT runtime without accepted QDT reports executed/rejected, not fixture;
  - non-scoreable fail-closed path reports no market prediction write.
- Clone-only smoke:
  - run one case against a temp DB;
  - verify active work drains to 0/0;
  - verify no generated artifacts persist after trap cleanup.

Success criteria:

- The current failure shape is reproducible without live DB mutation.
- Reports distinguish stage completion from readiness acceptance.
- Reports distinguish live model execution from deterministic/fixture fallback.
- Cleanup checks pass.

Checklist:

- [x] Baseline clone command documented in phase notes.
- [x] Live DB guard is tested.
- [x] Taxonomy tests pass.
- [x] No temp artifacts remain.
- [x] `git diff --check` passes.
- [x] Only intentional files are modified.

Completion note, 2026-07-01:

- Added a hard preflight guard to `run_ads_one_case_canary.py` / `ads_operational_canary.py`: known live DB control-state writes now require explicit `--allow-live-control-state-write`. Focused tests cover live-path refusal before control-state mutation, explicit allowance, and default clone-path operation.
- Added `ads-source-retrieval-pipeline-health-taxonomy/v1` to real-runtime canary reporting. It distinguishes `stage_completed_with_readiness_block` from accepted readiness, reports `non_scoreable_fail_closed`, and preserves the Phase 0 audit baseline as machine-checkable expectations.
- Baseline clone smoke used:

```bash
TMPDIR="$(mktemp -d /tmp/ads-v2-source-retrieval-phase0.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT
cp scripts/data/predquant.sqlite3 "$TMPDIR/predquant.sqlite3"
python3 scripts/bin/run_ads_one_case_canary.py \
  --db-path "$TMPDIR/predquant.sqlite3" \
  --handler-factory predquant.ads_production_handlers \
  --runner-mode non_executing_canary \
  --max-cases 1 \
  --allow-non-scoreable \
  --require-manifest-handoffs \
  --require-real-runtime-canary-criteria \
  --require-researcher-model-executed \
  --metadata-json '{"audit_id":"ads-v2-source-retrieval-phase0","live_db_mutation":"clone_only"}' \
  --apply \
  --pretty
```

- Clone proof run `ads-pipeline-run:1444f62f1ed9082d795935d7315fb5cc751110fb56d5fdbf8a4886355fd2a9b1` completed all 13 stages, drained active work to `0/0`, stayed clone-only, and failed closed at `retrieval_live_acceptance_requirements` plus `researcher_model_runtime_not_verified`.
- The clone proof reported `live_qdt_call_executed_output_accepted`, `retrieval_source_populated_but_not_certified`, `native_research_executed_no_candidates`, `stage_completed_with_readiness_block`, and `non_scoreable_fail_closed`. It wrote one non-scoreable forecast decision record, zero `market_predictions`, and zero `scae_ledger_outputs`.
- Verification passed: `test_ads_real_runtime_canary`, focused `test_ads_operational_canary` guard/full-stage taxonomy tests, `py_compile` for changed modules/tests, CLI help checks for canary/operator/real-runtime reports, cleanup check for phase temp directories, and `git diff --check`.

## Phase 1 - QDT Mechanical Repair And Persistence Hardening

Status: completed 2026-07-01

Goal: land the QDT fixes found during the audit so live Decomposer output can pass when the remaining
errors are mechanical rather than semantic.

Implementation:

- Preserve MIG-003 authority guardrails while allowing `repair_decision` only inside schema-repair
  diagnostics.
- Normalize `leaf_question` and `question_text` aliases after model repair.
- For analyst/economist consensus leaves:
  - repair temporal role to `pre_resolution_forecast_driver`;
  - repair coverage to `source_quality`;
  - rebuild research sufficiency from canonical templates instead of hand-editing one source class.
- Keep semantic failures non-repairable.

Pseudocode:

```python
def persistence_field_allowed(path, key, value):
    normalized = normalize_field(key)
    if normalized == "repair_decision" and "schema_repair_diagnostics" in path:
        return True
    return not forbidden_persistence_field(normalized, value)


def repair_leaf_aliases(leaf):
    if not leaf.get("question_text") and leaf.get("leaf_question"):
        leaf["question_text"] = leaf["leaf_question"]
    if leaf.get("question_text"):
        leaf["leaf_question"] = leaf["question_text"]
    return leaf


def repair_analyst_consensus_leaf(leaf):
    if looks_like_analyst_consensus(leaf):
        leaf["purpose"] = "direct_evidence"
        leaf["coverage_dimension"] = "source_quality"
        leaf["leaf_temporal_role"] = "pre_resolution_forecast_driver"
        ensure_consensus_evidence_field(leaf)
        leaf.pop("research_sufficiency_requirements", None)
    return leaf
```

Testing suite:

- Decomposer persistence tests:
  - allows `repair_decision` in schema-repair diagnostics;
  - still rejects active forecast/probability/decision authority fields.
- Runtime decomposition tests:
  - mismatched `leaf_question`/`question_text` is repaired;
  - analyst-consensus stale sufficiency is rebuilt to canonical independent/expert source classes;
  - semantic invalid output remains rejected.
- Focused command:

```bash
python3 -m unittest scripts.tests.test_runtime_decomposition scripts.tests.test_persistence scripts.tests.test_model_runtime
```

Success criteria:

- QDT live-shape fixture validates after one mechanical repair.
- No semantic or forbidden-authority failures are converted into valid QDTs.
- Clone-only QDT stage produces accepted live QDT artifact when model output is repairable.

Checklist:

- [x] Persistence guard remains strict.
- [x] Alias repair is covered.
- [x] Analyst-consensus canonical sufficiency is covered.
- [x] Focused decomposer tests pass.
- [x] Temp artifacts and scripts are deleted.
- [x] `git diff --check` passes.

Completion note, 2026-07-01:

- Preserved MIG-003 authority scanning while allowing `repair_decision` only inside `schema_repair_diagnostics`; active forecast/probability/decision authority fields remain rejected by the existing persistence guard.
- Normalized repaired model leaves so `leaf_question` follows canonical `question_text` after repair.
- Repaired analyst/economist consensus leaves to `direct_evidence` / `source_quality` / `pre_resolution_forecast_driver`, ensured consensus evidence fields are present, and forced canonical sufficiency rebuilding instead of preserving stale official-source classes.
- Added a live transport-response CLI regression proving a repairable live model payload writes an accepted `decomposer_model_runtime_live` QDT artifact after one mechanical repair.
- Verification passed: focused Decomposer Phase 1 suite (`test_runtime_decomposition`, `test_persistence`, `test_model_runtime`, 44 tests), full Decomposer discovery (116 tests), focused Orchestrator temp-DB canary QDT path test, `py_compile` for changed Decomposer files/tests, cleanup check for phase temp directories, and `git diff --check`.

## Phase 2 - Source Provider Abstraction And Runtime Artifact Persistence

Status: completed 2026-07-01

Goal: make source discovery a first-class provider layer, and make every model/search provider call
observable enough to diagnose failures.

Implementation:

- Introduce a provider interface for source discovery:
  - direct official URL candidates;
  - general web/browser search candidates;
  - native GPT research candidate discovery;
  - optional future provider hooks.
- Normalize provider outputs into candidate records with authority boundaries.
- Persist native research runtime call artifacts or bounded safe failure payloads.
- Attach per-leaf runtime refs to failure diagnostics.
- Ensure native research remains URL-candidate discovery only.

Pseudocode:

```python
class SourceDiscoveryProvider(Protocol):
    provider_id: str
    authority: SourceDiscoveryAuthority

    def discover(self, leaf, query_context, budget) -> ProviderResult:
        ...


def run_provider(provider, leaf, query_context, budget):
    started = now()
    try:
        result = provider.discover(leaf, query_context, budget)
        runtime_ref = persist_provider_runtime(provider, leaf, result)
        return normalize_candidates(result, runtime_ref)
    except Exception as exc:
        runtime_ref = persist_safe_failure(provider, leaf, exc, started)
        return ProviderResult(
            status="failed",
            runtime_ref=runtime_ref,
            safe_error=safe_error_summary(exc),
            candidates=[],
        )


def validate_native_candidate(candidate):
    forbid(candidate, ["probability", "forecast", "source_class_final", "research_sufficiency"])
    require_fetchable_url(candidate["url"])
```

Testing suite:

- Provider interface unit tests:
  - each provider returns normalized candidate records;
  - native provider output with forbidden authority is rejected;
  - provider failure persists safe runtime diagnostics.
- Retrieval transport tests:
  - native failure diagnostics contain leaf id, provider id, runtime ref, safe class, safe reason;
  - provider runtime refs are materialized in artifact manifest or packet references.
- Clone-only proof:
  - intentionally inject one provider failure;
  - verify other provider diagnostics remain complete and source discovery continues where allowed.

Success criteria:

- Native research failures are diagnosable without external logs.
- All provider output is normalized before admission.
- Native research cannot become evidence without deterministic fetch/admission.

Checklist:

- [x] Provider abstraction exists and is tested.
- [x] Native runtime call refs are persisted or safely summarized.
- [x] Forbidden native outputs are rejected.
- [x] Failure diagnostics include enough detail to act on.
- [x] Temp artifacts and scripts are deleted.
- [x] `git diff --check` passes.

Completion note, 2026-07-01:

- Added an explicit `SourceDiscoveryProvider` / `SourceDiscoveryProviderResult` contract and normalized direct URL, browser search, and native GPT research candidates with provider ids, provider kinds, authority boundaries, and runtime refs.
- Added bounded `ads-source-provider-runtime-ref/v1` records for direct, search, and native provider calls, including safe failure payloads for browser/native failures without granting source, sufficiency, or forecast authority.
- Kept native GPT research URL-candidate-only: forbidden source/sufficiency/forecast authority output is still rejected before fetch/admission, and native candidate discovery artifacts carry runtime refs without embedding forbidden authority fields in candidate payloads.
- Materialized source-provider runtime refs into retrieval transport diagnostics and retrieval packets so native failures and successful discoveries are diagnosable from packet artifacts.
- Verification passed: focused Orchestrator provider/native suite (`test_ads_retrieval_transport`, `test_ads_native_research`, 33 tests), full Orchestrator discovery (328 tests), full Researcher discovery (252 tests), `py_compile` for changed implementation/tests, and `git diff --check`.

## Phase 3 - Official And Direct Source Priority Adapters

Status: completed 2026-07-01

Goal: stop treating official/contract-critical source discovery as generic web search when structured
or predictable source routes exist.

Implementation:

- Add official/direct source adapters for:
  - Polymarket market/contract/rules text;
  - central bank policy pages and announcement calendars;
  - official schedule and rate decision pages;
  - known source domains per market category.
- Route protected-primary and resolution-mechanics leaves to official/direct adapters before generic
  search.
- Store adapter reason codes so downstream can see why official sources were targeted.
- Keep direct-source candidates subject to the same deterministic fetch/admission validators.

Pseudocode:

```python
def select_official_adapters(case, leaf):
    adapters = []
    if leaf.purpose in {"source_of_truth", "resolution_mechanics"}:
        adapters.append(PolymarketContractAdapter())
    if "Bank of Israel" in case.question or "BOI" in leaf.question:
        adapters.append(CentralBankAdapter(domain="boi.org.il"))
    return adapters


def discover_priority_sources(case, leaf, budget):
    official_results = []
    for adapter in select_official_adapters(case, leaf):
        official_results.extend(run_provider(adapter, leaf, case.query_context, budget.official))
    if official_results_meet_minimum(official_results, leaf):
        return official_results
    return official_results + run_generic_discovery(case, leaf, budget.remaining)
```

Testing suite:

- Adapter unit tests:
  - BOI source-of-truth leaves get official central bank adapter;
  - contract-resolution leaves get market contract adapter;
  - non-official leaves can still use generic search.
- Retrieval tests:
  - official/direct candidates are fetched deterministically;
  - direct official candidates do not bypass source-class/freshness validators.
- Clone-only proof:
  - BOI case shows official/direct adapter attempts before generic browser search.

Success criteria:

- Protected-primary leaves have official/direct discovery attempts.
- Contract/rule leaves do not depend solely on generic agent search.
- Official/direct routes improve candidate coverage without bypassing validation.

Checklist:

- [x] Official/direct adapters implemented.
- [x] Adapter routing is deterministic and tested.
- [x] Protected-primary leaves receive official/direct attempts.
- [x] Fetch/admission remains deterministic.
- [x] Temp artifacts and scripts are deleted.
- [x] `git diff --check` passes.

Completion note, 2026-07-01:

- Added deterministic official/direct adapter routing inside ADS retrieval transport for Bank of Israel protected-primary leaves and Polymarket contract/rules leaves.
- BOI adapter candidates now target official central-bank rate-decision and schedule pages before generic browser search when a BOI protected-primary leaf has no stronger embedded source URL.
- Polymarket resolution/source-of-truth leaves retain existing `case_contract.market_url` provenance while carrying adapter ids and reason codes for downstream diagnostics.
- Adapter diagnostics, candidate counts, fetch attempt counts, reason codes, known domains, and authority boundaries are reported without granting source metadata, sufficiency, temporal, or forecast authority.
- Direct adapter candidates still pass through the same fetch and deterministic admission validators; undated adapter fetches are rejected rather than admitted via direct-hint timestamp inference.
- Verification passed: focused Orchestrator retrieval transport suite (`test_ads_retrieval_transport`, 34 tests), `py_compile` for changed transport/test files, full Orchestrator discovery, temp cleanup check, and `git diff --check`.

## Phase 4 - Bounded Parallel Search And Separate Lane Budgets

Status: completed 2026-07-01

Goal: prevent one slow provider or one leaf from starving the rest of retrieval.

Implementation:

- Run leaf/provider discovery with bounded concurrency.
- Separate budgets for:
  - official/direct source discovery;
  - native research candidate discovery;
  - browser/general web search;
  - fetch/extraction;
  - metadata/claim validation.
- Prioritize critical/protected-primary leaves first.
- Preserve retry policy for retryable provider failures without consuming unrelated lane budgets.
- Add elapsed-budget diagnostics per lane, not only global retrieval elapsed time.

Pseudocode:

```python
def retrieval_schedule(leaves):
    return sorted(
        leaves,
        key=lambda leaf: (
            not leaf.protected_primary_required,
            leaf.priority_rank,
            leaf.leaf_id,
        ),
    )


async def run_discovery(leaves, budgets, concurrency):
    semaphore = Semaphore(concurrency.max_leaf_tasks)
    results = []
    for leaf in retrieval_schedule(leaves):
        async with semaphore:
            leaf_results = await run_leaf_lanes(
                leaf,
                official_budget=budgets.official.slice_for(leaf),
                native_budget=budgets.native.slice_for(leaf),
                browser_budget=budgets.browser.slice_for(leaf),
            )
            results.append(leaf_results)
    return results


def should_skip_lane(lane_budget, leaf):
    return lane_budget.exhausted_for_lane() or lane_budget.leaf_attempts_exhausted(leaf)
```

Testing suite:

- Scheduler unit tests:
  - protected-primary leaves are scheduled first;
  - browser budget exhaustion does not skip native or official lanes;
  - one provider failure does not mark unrelated leaves skipped.
- Timeout/budget tests:
  - injected slow provider times out within its lane;
  - remaining leaves continue under separate budgets.
- Clone-only proof:
  - BOI case attempts source discovery for all critical leaves even when browser provider has one
    failure.

Success criteria:

- Search skipped-by-elapsed-budget count is not caused by a single early slow provider.
- Provider failures are isolated to their provider/lane unless policy says otherwise.
- Critical leaves get attempts before low-priority leaves.

Checklist:

- [x] Bounded concurrency is implemented.
- [x] Separate lane budgets are implemented.
- [x] Critical-leaf ordering is tested.
- [x] Provider failure isolation is tested.
- [x] Temp artifacts and scripts are deleted.
- [x] `git diff --check` passes.

Completion note, 2026-07-01:

- Added a deterministic retrieval scheduler that orders protected-primary leaves first, then high-priority leaves, with explicit bounded leaf/provider lane concurrency policy knobs and scheduler diagnostics.
- Split retrieval transport diagnostics into lane-budget records for official/direct discovery, direct fetch/extraction, browser search, browser search fetch/extraction, native research discovery, native candidate fetch/extraction, and downstream metadata/claim validation.
- Changed browser search elapsed budgeting from one global search deadline to per-leaf browser-search lane windows, so one slow search provider call does not skip unrelated leaves; remaining variants for the same leaf can still be skipped when that leaf exhausts its elapsed budget.
- Preserved retry policy and leaf-scoped provider failure isolation while exposing elapsed-budget skip counts per lane.
- Verification passed: focused Orchestrator retrieval transport suite (`test_ads_retrieval_transport`, 36 tests), `py_compile` for changed transport/test files, full Orchestrator discovery, temp cleanup check, and `git diff --check`.

## Phase 5 - Fetch, Extraction, Claims, Freshness, And Source Families

Status: completed 2026-07-01

Goal: turn candidate URLs into classification-useful evidence, not just diagnostic chunks.

Implementation:

- Strengthen fetch/extraction so admitted evidence includes:
  - meaningful bounded excerpts;
  - canonical URL and source identity;
  - publication/update timestamp or explicit freshness failure;
  - source class;
  - source family;
  - claim candidates;
  - claim family fingerprints.
- Keep short/hash-only chunks diagnostic only.
- Attempt deterministic claim extraction before breadth certification.
- Make evidence counted for breadth only when it passes usefulness and metadata gates.

Pseudocode:

```python
def extract_evidence(fetch_result, leaf):
    content = normalize_html_or_text(fetch_result.body)
    excerpt = select_relevant_excerpt(content, leaf.required_value_fields)
    metadata = resolve_source_metadata(fetch_result.url, content)
    claims = extract_atomic_claims(excerpt, leaf)
    return EvidenceChunk(
        text=excerpt.text,
        source_metadata=metadata,
        claim_candidates=claims,
        usefulness=classify_usefulness(excerpt, claims, metadata),
    )


def admit_for_breadth(chunk, requirement):
    if chunk.usefulness != "classification_useful":
        return diagnostic_only("not_classification_useful")
    if not chunk.claim_candidates:
        return diagnostic_only("claim_extraction_not_attempted_or_empty")
    if not source_class_matches(chunk, requirement):
        return diagnostic_only("required_source_class_missing")
    if freshness_required(requirement) and not freshness_satisfied(chunk):
        return diagnostic_only("freshness_not_met")
    return admitted_for_breadth(chunk)
```

Testing suite:

- Extraction tests:
  - meaningful page content yields bounded excerpt above minimum length;
  - hash-only/short snippets are diagnostic only;
  - claim extraction creates claim candidates and claim families;
  - source metadata resolves source class and source family.
- Freshness tests:
  - dated current official source satisfies freshness;
  - stale or undated source blocks freshness-required leaves.
- Sufficiency tests:
  - leaf certifies only when admitted evidence, claim families, source families, source class, and
    freshness requirements are met.
- Clone-only proof:
  - retrieval packet has nonzero meaningful snippets and at least one certified leaf before
    researcher dispatch is enabled.

Success criteria:

- `meaningful_snippet_admitted_count > 0`.
- `claim_family_count > 0` for certified leaves.
- `source_family_count > 0` for certified leaves.
- short/hash-only chunks do not count toward breadth.
- protected-primary and freshness gates remain strict.

Checklist:

- [x] Fetch/extraction produces meaningful bounded excerpts.
- [x] Claim extraction is attempted and tested.
- [x] Source metadata/family resolution is tested.
- [x] Freshness gates are tested.
- [x] Sufficiency certification accepts only useful evidence.
- [x] Temp artifacts and scripts are deleted.
- [x] `git diff --check` passes.

Completion note, 2026-07-01:

- Tightened deterministic provenance admission so evidence counts toward breadth only after source class, source family, claim family, temporal pass, independence, and context-usefulness gates all pass.
- Added hash-like payload detection so hash-only content stays diagnostic-only even when a fetch returns non-empty text, while short bounded excerpts remain excluded from research-useful coverage.
- Recorded per-evidence claim extraction status/counts and source excerpt status/counts during fetch materialization.
- Added finalized runtime summary counters for meaningful admitted snippets, diagnostic-only snippets, deterministic claim extraction attempts, and claim/source families on certified leaves.
- Expanded focused retrieval tests for certified fetched evidence, source metadata/family/freshness certification, claim extraction, and short/hash-only diagnostic-only chunks.
- Verification passed: focused Phase 5 retrieval tests, full Researcher discovery (`253` tests), full Orchestrator discovery (`334` tests), `py_compile` for changed Researcher files, temp cleanup check, and `git diff --check`.

## Phase 6 - Researcher Dispatch Positive Path

Status: pending

Goal: unblock researcher classification only after retrieval sufficiency certifies, and prove that
researcher output is real, bounded, and verification-ready.

Implementation:

- Keep researcher dispatch blocked when any required leaf lacks a valid sufficiency certificate.
- When certificates pass, dispatch researchers with bounded evidence packets only.
- Require researcher sidecars to include:
  - model runtime provenance;
  - evidence refs used;
  - classification status;
  - uncertainty;
  - source authority;
  - no probability/fair-value/SCAE-delta fields.
- Persist classification slices only from valid sidecars.

Pseudocode:

```python
def maybe_dispatch_researcher(case, retrieval_packet):
    certs = retrieval_packet["leaf_research_sufficiency_certificates"]
    if not all_required_certs_dispatchable(certs):
        return readiness_block("retrieval_sufficiency_not_certified")
    assignments = build_researcher_assignments(retrieval_packet)
    return run_researcher_runtime(assignments)


def persist_researcher_sidecar(sidecar):
    forbid(sidecar, ["probability", "fair_value", "scae_delta", "decision"])
    require(sidecar, ["model_runtime_ref", "evidence_refs", "classification_status"])
    return write_classification_slices(sidecar)
```

Testing suite:

- Researcher assignment tests:
  - uncertified retrieval blocks dispatch;
  - certified retrieval creates assignments with bounded evidence only.
- Researcher runtime tests:
  - model execution provenance is required;
  - forbidden probability/SCAE fields fail validation.
- Verification bridge tests:
  - valid researcher sidecars create classification slices;
  - invalid sidecars create readiness blocks.
- Clone-only proof:
  - once at least representative required leaves certify, researcher classification emits nonzero
    classification slices.

Success criteria:

- Researcher remains blocked for uncertified retrieval.
- Certified retrieval produces researcher model execution.
- Classification slices are nonzero only when sidecars validate.
- No researcher artifact contains forecast authority.

Checklist:

- [ ] Uncertified retrieval block remains tested.
- [ ] Certified dispatch positive path is tested.
- [ ] Researcher provenance is required.
- [ ] Forbidden authority scan is tested.
- [ ] Temp artifacts and scripts are deleted.
- [ ] `git diff --check` passes.

## Phase 7 - AMRG Consumption And Reporting Accuracy

Status: pending

Goal: keep AMRG advisory while making its consumption and readiness status accurate across QDT and
retrieval.

Implementation:

- Normalize AMRG operator report lifecycle:
  - initial context creation may be `pending_decomposition`;
  - post-QDT report must become `evaluated`;
  - consumed/ignored hint counts must reflect accepted QDT refs.
- Add retrieval query hint consumption reporting without granting retrieval sufficiency authority.
- Keep vector-unavailable weak mode explicit.
- Keep AMRG model assist `not_requested` unless policy changes.

Pseudocode:

```python
def finalize_amrg_consumption(amrg_context, qdt, retrieval_packet=None):
    consumed_refs = refs_used_by_qdt(qdt)
    retrieval_refs = refs_used_by_retrieval_queries(retrieval_packet)
    return {
        "decomposer_consumption_status": "evaluated",
        "consumed_hint_count": len(consumed_refs),
        "ignored_hint_count": len(all_refs(amrg_context) - consumed_refs),
        "retrieval_hint_consumption_count": len(retrieval_refs),
        "authority": "context_ref_only_no_forecast_authority",
    }
```

Testing suite:

- AMRG context tests:
  - consumed QDT refs update operator report;
  - ignored refs get reason codes;
  - retrieval query hint usage is reported as query context only.
- Authority tests:
  - AMRG refs cannot count toward retrieval sufficiency;
  - AMRG refs cannot create SCAE deltas or probability authority.
- Clone-only proof:
  - AMRG report shows evaluated consumption after QDT, not stale pending state.

Success criteria:

- AMRG report state matches accepted QDT artifact.
- AMRG weak-context authority is preserved.
- Vector and assist status are explicit and not overclaimed.

Checklist:

- [ ] AMRG consumption finalization is implemented.
- [ ] QDT consumed/ignored counts are tested.
- [ ] Retrieval hint usage remains authority-bounded.
- [ ] Assist not-requested status is not claimed as executed.
- [ ] Temp artifacts and scripts are deleted.
- [ ] `git diff --check` passes.

## Phase 8 - SCAE, Decision, Training Trace, And Replay Authority Proof

Status: pending

Goal: prove downstream stages remain fail-closed for insufficient inputs and produce valid artifacts
only with verified SCAE-ready deltas.

Implementation:

- Keep SCAE invalid when:
  - retrieval is uncertified;
  - researcher classification is blocked;
  - verification emits no SCAE-ready deltas.
- Require valid SCAE ledger to include evidence delta refs.
- Require decision gate to write market predictions only for valid scoreable forecasts in the
  appropriate mode.
- Keep training trace and replay records non-scoreable when upstream is non-scoreable.

Pseudocode:

```python
def build_scae_ledger(verified_slices):
    if not verified_slices:
        return scae_fail_closed("no_verified_evidence_delta_refs")
    deltas = compute_scae_deltas(verified_slices)
    return valid_scae_ledger(deltas)


def decision_gate(scae_ledger, runner_mode):
    if scae_ledger.forecast_validity_status != "valid_for_forecast":
        return decision_block("blocked_invalid_scae_forecast")
    if runner_mode == "non_executing_canary":
        return decision_non_executing(scae_ledger)
    return persist_market_prediction(scae_ledger)
```

Testing suite:

- SCAE tests:
  - no deltas means invalid forecast;
  - valid verification deltas produce valid ledger;
  - non-SCAE components cannot write probabilities.
- Decision tests:
  - invalid SCAE writes no market prediction;
  - valid non-executing mode does not mutate live prediction table unless expected by canary mode;
  - scoreable mode writes exactly one prediction in clone proof.
- Training/replay tests:
  - non-scoreable cases record readiness/non-scoreable reason codes;
  - scoreable cases preserve manifest lineage.

Success criteria:

- Fail-closed path remains intact.
- Positive path is available only after verified deltas.
- Protected write deltas match runner mode expectations.

Checklist:

- [ ] Invalid upstream fail-closed tests pass.
- [ ] Valid-delta SCAE positive tests pass.
- [ ] Decision write rules are tested.
- [ ] Training/replay lineage is tested.
- [ ] Temp artifacts and scripts are deleted.
- [ ] `git diff --check` passes.

## Phase 9 - Operator Reporting, Handoffs, And Health Semantics

Status: pending

Goal: make operator-facing reports explain pipeline health accurately across stage completion,
readiness blocks, model execution, and protected writes.

Implementation:

- Add summary fields:
  - `stage_completion_count`
  - `readiness_block_count`
  - `accepted_intelligence_stage_count`
  - `live_model_call_count`
  - `live_model_call_failed_count`
  - `certified_retrieval_leaf_count`
  - `classification_slice_count`
  - `scae_delta_ref_count`
  - `protected_write_deltas`
- Make handoff reports distinguish:
  - artifact exists;
  - artifact valid;
  - artifact accepted for downstream;
  - artifact is a readiness block.
- Add clear top-level postflight reason ordering.

Pseudocode:

```python
def summarize_pipeline_health(run):
    stages = load_stage_events(run)
    artifacts = load_case_artifacts(run)
    return {
        "stage_completion_count": count_completed(stages),
        "readiness_block_count": count_readiness_blocks(artifacts),
        "accepted_intelligence_stage_count": count_accepted_intelligence(artifacts),
        "handoff_health": summarize_handoffs(stages, artifacts),
        "protected_write_deltas": protected_write_delta_summary(run),
    }


def handoff_status(artifact):
    if artifact.type.endswith("_readiness_block"):
        return "valid_readiness_block_not_downstream_accepted"
    if artifact.validation_status == "valid" and accepted_by_downstream(artifact):
        return "valid_and_accepted"
    return "valid_not_accepted"
```

Testing suite:

- Report tests:
  - completed stages plus readiness blocks are clearly reported;
  - live rejected QDT does not report as fixture;
  - retrieval source-populated but uncertified is distinct from retrieval not executed.
- Handoff tests:
  - valid readiness block is not counted as accepted downstream input;
  - missing artifact refs fail manifest checks.
- CLI smoke:
  - real-runtime canary report;
  - operator review;
  - handoff report;
  - live-readiness report.

Success criteria:

- Reports make it obvious whether the pipeline completed, accepted, blocked, or failed.
- No report overclaims model execution, AMRG assist, retrieval certification, researcher execution,
  or SCAE validity.
- Handoff health is visible per phase.

Checklist:

- [ ] New report fields are implemented.
- [ ] Handoff acceptance semantics are tested.
- [ ] CLI smoke tests pass.
- [ ] No report overclaims authority or execution.
- [ ] Temp artifacts and scripts are deleted.
- [ ] `git diff --check` passes.

## Phase 10 - Representative Clone Batch And Closure

Status: pending

Goal: prove the full current-shape pipeline across representative cases, then close or update this
plan based on observed results.

Implementation:

- Run a representative clone-only batch:
  - BOI rate decrease style case;
  - another central-bank/macro case;
  - a non-central-bank market requiring different source adapters;
  - one case expected to remain non-scoreable due to valid insufficiency.
- Produce aggregate report with:
  - QDT live accepted count;
  - native provider success/failure counts;
  - official/direct adapter success counts;
  - certified retrieval leaf counts;
  - researcher classification counts;
  - SCAE valid/invalid counts;
  - protected write deltas;
  - cleanup status.
- If any new failure pattern appears, add a dated amendment before closure.

Pseudocode:

```bash
TMPDIR="$(mktemp -d /tmp/ads-v2-source-retrieval-phase10.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT

# Copy DB into "$TMPDIR".
# Run representative cases using existing canary/report CLIs.
# Write reports under "$TMPDIR".
# Aggregate counters under "$TMPDIR".
# Assert cleanup before phase completion.
```

```python
def aggregate_clone_batch(reports):
    return {
        "cases": len(reports),
        "qdt_live_accepted": count(r.qdt_state == "live_qdt_call_executed_output_accepted" for r in reports),
        "retrieval_certified_cases": count(r.certified_leaf_count > 0 for r in reports),
        "researcher_executed_cases": count(r.classification_slice_count > 0 for r in reports),
        "valid_scae_cases": count(r.scae_valid_forecast_count > 0 for r in reports),
        "unexpected_failure_count": count_unexpected_failures(reports),
        "protected_write_delta_summary": summarize_protected_deltas(reports),
    }
```

Testing suite:

- Full focused test pass across touched repos:
  - decomposer relevant discovery;
  - researcher-swarm relevant discovery;
  - orchestrator canary/report/retrieval tests;
  - SCAE authority tests.
- Representative clone batch:
  - no live DB mutation;
  - no active runs/leases left;
  - no unexpected protected writes;
  - scoreable positive path only when expected;
  - valid insufficiency remains non-scoreable when expected.
- Cleanup proof:
  - temp dirs removed;
  - generated artifacts not staged;
  - one-off scripts deleted.

Success criteria:

- Representative cases no longer fail because source search/retrieval is underpowered.
- Native research either returns fetchable candidates or produces useful safe failure diagnostics.
- Retrieval certificates correctly distinguish certified, stale, insufficient, and structurally
  unanswerable leaves.
- Researcher, SCAE, decision, training trace, and replay follow the certified upstream state.
- Operator reports explain outcomes without manual artifact spelunking.

Checklist:

- [ ] Representative clone batch completed.
- [ ] Aggregate report reviewed.
- [ ] New blockers added as amendments or follow-up issues.
- [ ] All expected tests pass.
- [ ] Cleanup proof passes.
- [ ] `git diff --check` passes.
- [ ] Plan closure note added.

## Final Completion Definition

The plan is complete only when:

- QDT live execution and accepted QDT artifacts are distinguished and working.
- Source discovery uses provider abstraction, official/direct priority, bounded parallelism, and
  separate lane budgets.
- Native research call artifacts or safe failure details are persisted.
- Fetch/extraction produces classification-useful evidence when sources support it.
- Retrieval certificates can certify leaves for real, and block leaves for clear reasons when not.
- Researcher classification executes only after certified retrieval.
- SCAE remains fail-closed for insufficient inputs and valid only after verified deltas.
- AMRG remains advisory and accurately reports consumption.
- Operator reports accurately separate stage completion, readiness blocks, downstream acceptance, and
  protected writes.
- Clone-only safety prevents accidental live control-state mutation.
- All testing artifacts and one-off testing scripts are deleted after successful tests.
